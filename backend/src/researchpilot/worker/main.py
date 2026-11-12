"""Worker process: job execution, outbox dispatch and run supervision.

Run with ``python -m researchpilot.worker``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import traceback
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime, timedelta
from typing import Any

import httpx
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.core.clock import Clock, SystemClock
from researchpilot.core.logging import configure_logging, get_logger
from researchpilot.core.settings import Settings, get_settings
from researchpilot.db.session import make_engine, make_sessionmaker, session_scope
from researchpilot.domain.enums import RunStatus
from researchpilot.events.outbox import Dispatcher
from researchpilot.integrations.registry import Sources, build_sources
from researchpilot.jobs import queue
from researchpilot.llm.factory import build_runtime_gateway
from researchpilot.llm.gateway import LLMGateway
from researchpilot.relations import tombstones
from researchpilot.runs import service
from researchpilot.services.dates.announcements import capture, categories_to_capture
from researchpilot.workflows.runner import WorkflowRunner

JobHandler = Callable[[queue.ClaimedJob], Coroutine[Any, Any, Any]]


def libpq_url(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


async def open_checkpointer(settings: Settings) -> tuple[AsyncPostgresSaver, AsyncConnectionPool]:
    """LangGraph's checkpointer, confined to the ``langgraph`` schema (migration 0002)."""
    pool = AsyncConnectionPool(
        libpq_url(settings.database_url),
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "prepare_threshold": 0,
            "options": "-c search_path=langgraph",
        },
        min_size=1,
        max_size=4,
        open=False,
    )
    await pool.open()
    saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
    await saver.setup()
    return saver, pool


ARXIV_CAPTURE_JOB = "arxiv_announcement_capture"
TOMBSTONE_PURGE_JOB = "tombstone_purge"
# No graph database before R2: markers cannot be verified absent yet (§12.6a).
GRAPH_BACKEND_ENABLED = False


class Worker:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        runner: WorkflowRunner,
        dispatcher: Dispatcher,
        sources: Sources | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self._settings = settings
        self._sessions = sessions
        self._runner = runner
        self._dispatcher = dispatcher
        self._sources = sources
        self._clock: Clock = clock or SystemClock()
        self._log = get_logger(component="worker", worker=self.id)
        self._handlers: dict[str, JobHandler] = {
            "run_workflow": self._run_workflow,
            "resume_workflow": self._run_workflow,
            ARXIV_CAPTURE_JOB: self._capture_announcements,
            TOMBSTONE_PURGE_JOB: self._purge_tombstones,
        }

    async def _run_workflow(self, job: queue.ClaimedJob) -> None:
        run_id = uuid.UUID(job.payload["run_id"])
        await self._runner.execute(run_id, resume=job.payload.get("resume"))

    async def _capture_announcements(self, job: queue.ClaimedJob) -> None:
        if self._sources is None:
            raise RuntimeError("the worker has no source clients")
        async with session_scope(self._sessions) as session:
            categories = await categories_to_capture(
                session, self._settings.arxiv_announcement_categories
            )
        report = await capture(self._sessions, self._sources.arxiv_feed, categories)
        self._log.info(
            "arxiv.capture_job_done",
            categories=report.categories,
            logged=report.logged,
            events=report.events_added,
        )

    async def _purge_tombstones(self, job: queue.ClaimedJob) -> None:
        async with session_scope(self._sessions) as session:
            report = await tombstones.purge(
                session, self._clock.now(), graph_enabled=GRAPH_BACKEND_ENABLED
            )
        self._log.info("tombstones.purge_job_done", purged=report.purged)

    async def schedule_maintenance(self, now: datetime | None = None) -> bool:
        """Enqueues today's deletion-marker purge once (idempotent per UTC day)."""
        now = now or self._clock.now()
        async with session_scope(self._sessions) as session:
            job = await queue.enqueue_once(
                session,
                TOMBSTONE_PURGE_JOB,
                {"day": now.date().isoformat()},
                dedupe_key=f"{TOMBSTONE_PURGE_JOB}:{now.date().isoformat()}",
            )
        return job is not None

    async def schedule_periodic(self, now: datetime | None = None) -> bool:
        """Enqueues today's announcement capture once, after the feeds are rebuilt."""
        if not self._settings.arxiv_capture_enabled or self._sources is None:
            return False
        now = now or self._clock.now()
        if now.hour < self._settings.arxiv_capture_after_utc_hour:
            return False
        async with session_scope(self._sessions) as session:
            job = await queue.enqueue_once(
                session,
                ARXIV_CAPTURE_JOB,
                {"day": now.date().isoformat()},
                dedupe_key=f"{ARXIV_CAPTURE_JOB}:{now.date().isoformat()}",
            )
        return job is not None

    async def run_forever(self, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        self._log.info("worker.started")
        while not stop.is_set():
            worked = await self.tick()
            if not worked:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), self._settings.worker_poll_seconds)

    async def tick(self) -> bool:
        """One unit of work: dispatch outbox events, fail exhausted stale jobs, then run at
        most one job."""
        dispatched = await self._dispatcher.dispatch_once()
        await self.schedule_periodic()
        await self.schedule_maintenance()
        stale = timedelta(seconds=self._settings.job_stale_after_seconds)
        failed = await self._fail_exhausted(stale)
        async with session_scope(self._sessions) as session:
            job = await queue.claim(session, self.id, stale)
        if job is None:
            return dispatched > 0 or failed > 0
        await self._process(job)
        return True

    async def _fail_exhausted(self, stale: timedelta) -> int:
        """Jobs whose worker died on their last attempt become failed, and so do their runs
        (unless the run already finished, e.g. was cancelled)."""
        async with session_scope(self._sessions) as session:
            payloads = await queue.fail_exhausted_stale(session, stale)
            for payload in payloads:
                if "run_id" in payload:
                    await service.finish(
                        session,
                        uuid.UUID(payload["run_id"]),
                        RunStatus.FAILED,
                        "The run stopped because the worker processing it stopped responding",
                        error={"type": "WorkerLost", "detail": "retry limit reached"},
                    )
        for payload in payloads:
            self._log.error("job.exhausted_after_worker_loss", payload=payload)
        return len(payloads)

    async def _process(self, job: queue.ClaimedJob) -> None:
        log = self._log.bind(job_id=str(job.id), kind=job.kind, attempt=job.attempts)
        handler = self._handlers.get(job.kind)
        cancelled_run = asyncio.Event()
        work: asyncio.Task[Any] | None = None
        beat: asyncio.Task[None] | None = None
        try:
            if handler is None:
                raise RuntimeError(f"no handler for job kind {job.kind!r}")
            work = asyncio.create_task(handler(job))
            beat = asyncio.create_task(self._heartbeat(job, work, cancelled_run))
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                if not cancelled_run.is_set():
                    work.cancel()  # worker shutting down: the job stays locked and is
                    raise  # reclaimed by another worker once its heartbeat is stale
                log.info("job.stopped_because_run_cancelled")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("job.failed", error=str(exc), trace=traceback.format_exc())
            async with session_scope(self._sessions) as session:
                final = await queue.fail(session, job, self.id, f"{type(exc).__name__}: {exc}")
                if final and "run_id" in job.payload:
                    await service.finish(
                        session,
                        uuid.UUID(job.payload["run_id"]),
                        RunStatus.FAILED,
                        "The run stopped because of an internal error",
                        error={"type": type(exc).__name__, "detail": str(exc)},
                    )
        else:
            async with session_scope(self._sessions) as session:
                await queue.complete(session, job.id, self.id)
            log.info("job.succeeded")
        finally:
            if beat is not None:
                beat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await beat

    async def _heartbeat(
        self, job: queue.ClaimedJob, work: asyncio.Task[Any], cancelled_run: asyncio.Event
    ) -> None:
        """Keeps the job lock alive and stops the job promptly if its run is cancelled."""
        run_id = uuid.UUID(job.payload["run_id"]) if "run_id" in job.payload else None
        while not work.done():
            await asyncio.sleep(self._settings.job_heartbeat_seconds)
            async with session_scope(self._sessions) as session:
                await queue.heartbeat(session, job.id, self.id)
                if run_id is not None:
                    await service.touch(session, run_id)
                    if await service.is_cancelled(session, run_id):
                        cancelled_run.set()
                        work.cancel()
                        return


def register_consumers(dispatcher: Dispatcher) -> None:
    """R0 has no business consumers yet; R1 adds assessment, staleness, etc."""


async def build_worker(
    settings: Settings,
    llm: LLMGateway | None = None,
    source_transport: httpx.AsyncBaseTransport | None = None,
    *,
    source_rate_limits: bool = True,
    clock: Clock | None = None,
) -> tuple[Worker, Callable[[], Awaitable[None]]]:
    engine = make_engine(settings.database_url)
    sessions = make_sessionmaker(engine)
    saver, pool = await open_checkpointer(settings)
    runner = WorkflowRunner(sessions, llm or build_runtime_gateway(settings), saver)
    dispatcher = Dispatcher(sessions)
    register_consumers(dispatcher)
    sources = build_sources(settings, sessions, source_transport, rate_limits=source_rate_limits)

    async def close() -> None:
        await sources.aclose()
        await pool.close()
        await engine.dispose()

    return Worker(settings, sessions, runner, dispatcher, sources, clock), close


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json, settings.secret_values())
    worker, close = await build_worker(settings)
    try:
        await worker.run_forever()
    finally:
        await close()
