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
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.core.logging import configure_logging, get_logger
from researchpilot.core.settings import Settings, get_settings
from researchpilot.db.session import make_engine, make_sessionmaker, session_scope
from researchpilot.domain.enums import RunStatus
from researchpilot.events.outbox import Dispatcher
from researchpilot.jobs import queue
from researchpilot.llm.factory import build_runtime_gateway
from researchpilot.llm.gateway import LLMGateway
from researchpilot.runs import service
from researchpilot.workflows.runner import WorkflowRunner

JobHandler = Callable[[queue.ClaimedJob], Awaitable[Any]]


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


class Worker:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        runner: WorkflowRunner,
        dispatcher: Dispatcher,
    ) -> None:
        self.id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self._settings = settings
        self._sessions = sessions
        self._runner = runner
        self._dispatcher = dispatcher
        self._log = get_logger(component="worker", worker=self.id)
        self._handlers: dict[str, JobHandler] = {
            "run_workflow": self._run_workflow,
            "resume_workflow": self._run_workflow,
        }

    async def _run_workflow(self, job: queue.ClaimedJob) -> None:
        run_id = uuid.UUID(job.payload["run_id"])
        await self._runner.execute(run_id, resume=job.payload.get("resume"))

    async def run_forever(self, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        self._log.info("worker.started")
        while not stop.is_set():
            worked = await self.tick()
            if not worked:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), self._settings.worker_poll_seconds)

    async def tick(self) -> bool:
        """One unit of work: dispatch outbox events, then run at most one job."""
        dispatched = await self._dispatcher.dispatch_once()
        async with session_scope(self._sessions) as session:
            job = await queue.claim(
                session, self.id, timedelta(seconds=self._settings.job_stale_after_seconds)
            )
        if job is None:
            return dispatched > 0
        await self._process(job)
        return True

    async def _process(self, job: queue.ClaimedJob) -> None:
        log = self._log.bind(job_id=str(job.id), kind=job.kind, attempt=job.attempts)
        handler = self._handlers.get(job.kind)
        beat = asyncio.create_task(self._heartbeat(job))
        try:
            if handler is None:
                raise RuntimeError(f"no handler for job kind {job.kind!r}")
            await handler(job)
        except asyncio.CancelledError:
            raise  # worker shutting down: leave the job locked; it is reclaimed when stale
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
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat

    async def _heartbeat(self, job: queue.ClaimedJob) -> None:
        while True:
            await asyncio.sleep(self._settings.job_heartbeat_seconds)
            async with session_scope(self._sessions) as session:
                await queue.heartbeat(session, job.id, self.id)
                if "run_id" in job.payload:
                    await service.touch(session, uuid.UUID(job.payload["run_id"]))


def register_consumers(dispatcher: Dispatcher) -> None:
    """R0 has no business consumers yet; R1 adds assessment, staleness, etc."""


async def build_worker(
    settings: Settings, llm: LLMGateway | None = None
) -> tuple[Worker, Callable[[], Awaitable[None]]]:
    engine = make_engine(settings.database_url)
    sessions = make_sessionmaker(engine)
    saver, pool = await open_checkpointer(settings)
    runner = WorkflowRunner(sessions, llm or build_runtime_gateway(settings), saver)
    dispatcher = Dispatcher(sessions)
    register_consumers(dispatcher)

    async def close() -> None:
        await pool.close()
        await engine.dispose()

    return Worker(settings, sessions, runner, dispatcher), close


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json, settings.secret_values())
    worker, close = await build_worker(settings)
    try:
        await worker.run_forever()
    finally:
        await close()
