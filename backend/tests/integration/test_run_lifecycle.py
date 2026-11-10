"""Cancellation and retry-limit guarantees for runs and jobs.

* A run cancelled while a workflow step is executing stays cancelled: the worker stops the job
  cooperatively and can no longer move the run to another state.
* Repeated hard worker crashes cannot exceed a job's retry limit; the exhausted job and its
  run end in a failed state.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta

import httpx
import pytest
import sqlalchemy as sa

from researchpilot.core.settings import Settings
from researchpilot.db.session import make_engine, make_sessionmaker, session_scope
from researchpilot.domain.enums import RunStatus
from researchpilot.jobs import queue
from researchpilot.runs import service
from researchpilot.worker.main import build_worker
from tests.integration.conftest import API, WorkerHandle, create_project, wait_for_status

pytestmark = pytest.mark.integration


async def _events(client: httpx.AsyncClient, run_id: str) -> list[dict[str, object]]:
    return list((await client.get(f"{API}/runs/{run_id}/events/log")).json())


async def _job(settings: Settings, run_id: str) -> dict[str, object]:
    engine = make_engine(settings.database_url)
    try:
        async with make_sessionmaker(engine)() as session:
            row = (
                (
                    await session.execute(
                        sa.text(
                            "SELECT status, attempts, max_attempts, last_error FROM jobs "
                            "WHERE payload->>'run_id' = :r ORDER BY created_at LIMIT 1"
                        ),
                        {"r": run_id},
                    )
                )
                .mappings()
                .one()
            )
        return dict(row)
    finally:
        await engine.dispose()


async def _poll(check: Callable[[], Awaitable[bool]], limit_seconds: float) -> None:
    async with asyncio.timeout(limit_seconds):
        while True:
            if await check():
                return
            await asyncio.sleep(0.05)


async def test_cancel_while_step_is_executing(
    client: httpx.AsyncClient,
    settings: Settings,
    start_worker: Callable[[], Awaitable[WorkerHandle]],
) -> None:
    project_id = await create_project(client)
    run_id = (
        await client.post(
            f"{API}/projects/{project_id}/runs",
            json={"workflow": "dummy", "config": {"pause_seconds": 4}},
        )
    ).json()["id"]
    await start_worker()

    async def step_started() -> bool:  # the 'prepare' step is executing
        return "step.started" in [e["type"] for e in await _events(client, run_id)]

    await _poll(step_started, 10)

    loop = asyncio.get_running_loop()
    cancelled_at = loop.time()
    assert (await client.post(f"{API}/runs/{run_id}/cancel")).status_code == 202

    # The worker stops the job promptly (heartbeat 0.2 s), well before the 4 s step ends.
    async def job_stopped() -> bool:
        return (await _job(settings, run_id))["status"] != "running"

    await _poll(job_stopped, 3)
    assert loop.time() - cancelled_at < 3

    # Wait past the step's natural end: nothing may move the run out of CANCELLED.
    await asyncio.sleep(4.5)
    run = (await client.get(f"{API}/runs/{run_id}")).json()
    assert run["status"] == "cancelled"
    types = [e["type"] for e in await _events(client, run_id)]
    after_cancel = types[types.index("run.cancelled") + 1 :]
    assert after_cancel == []
    assert not {"run.succeeded", "checkpoint.opened", "step.completed"} & set(types)
    assert (await client.get(f"{API}/runs/{run_id}/checkpoints")).json() == []
    assert (await _job(settings, run_id))["status"] == "succeeded"  # stopped cleanly, no retry


async def test_workflow_stops_itself_even_without_worker_interruption(
    client: httpx.AsyncClient,
    settings: Settings,
) -> None:
    """Cooperative path alone (no heartbeat): the runner finishes its step, sees the
    cancellation at the next cancellation point, and leaves the run cancelled."""
    project_id = await create_project(client)
    run_id = uuid.UUID(
        (
            await client.post(
                f"{API}/projects/{project_id}/runs",
                json={"workflow": "dummy", "config": {"pause_seconds": 1}},
            )
        ).json()["id"]
    )
    worker, close = await build_worker(settings)
    try:
        execute = asyncio.create_task(worker._runner.execute(run_id))
        await wait_for_status(client, str(run_id), {"running"})
        assert (await client.post(f"{API}/runs/{run_id}/cancel")).status_code == 202
        assert await execute is RunStatus.CANCELLED
    finally:
        await close()
    assert (await client.get(f"{API}/runs/{run_id}")).json()["status"] == "cancelled"


async def test_terminal_runs_cannot_change_state(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    project_id = await create_project(client)
    run_id = uuid.UUID(
        (await client.post(f"{API}/projects/{project_id}/runs", json={"workflow": "dummy"})).json()[
            "id"
        ]
    )
    assert (await client.post(f"{API}/runs/{run_id}/cancel")).status_code == 202
    engine = make_engine(settings.database_url)
    try:
        async with session_scope(make_sessionmaker(engine)) as session:
            assert await service.mark_running(session, run_id) is False
            assert await service.open_checkpoint(session, run_id, "x", {}) is None
            assert await service.finish(session, run_id, RunStatus.SUCCEEDED, "x") is False
    finally:
        await engine.dispose()
    assert (await client.get(f"{API}/runs/{run_id}")).json()["status"] == "cancelled"
    assert (await client.post(f"{API}/runs/{run_id}/cancel")).status_code == 422


async def test_cancel_while_awaiting_approval_closes_the_checkpoint(
    client: httpx.AsyncClient,
    start_worker: Callable[[], Awaitable[WorkerHandle]],
) -> None:
    project_id = await create_project(client)
    run_id = (
        await client.post(f"{API}/projects/{project_id}/runs", json={"workflow": "dummy"})
    ).json()["id"]
    await start_worker()
    await wait_for_status(client, run_id, {"awaiting_approval"})
    checkpoint = (await client.get(f"{API}/runs/{run_id}/checkpoints")).json()[0]
    assert (await client.post(f"{API}/runs/{run_id}/cancel")).status_code == 202

    closed = (await client.get(f"{API}/runs/{run_id}/checkpoints")).json()[0]
    assert closed["status"] == "rejected"
    late = await client.post(
        f"{API}/checkpoints/{checkpoint['id']}/decision", json={"status": "approved"}
    )
    assert late.status_code == 422
    assert (await client.get(f"{API}/runs/{run_id}")).json()["status"] == "cancelled"


async def test_repeated_hard_crashes_stop_at_the_retry_limit(
    client: httpx.AsyncClient,
    settings: Settings,
) -> None:
    """Each simulated crash claims the job and then stops heartbeating. The job may be
    reclaimed only while attempts remain; after the limit, the job and its run fail."""
    project_id = await create_project(client)
    run_id = (
        await client.post(f"{API}/projects/{project_id}/runs", json={"workflow": "dummy"})
    ).json()["id"]
    stale = timedelta(seconds=settings.job_stale_after_seconds)
    engine = make_engine(settings.database_url)
    sessions = make_sessionmaker(engine)

    async def crash_once(n: int) -> queue.ClaimedJob | None:
        async with session_scope(sessions) as session:
            job = await queue.claim(session, f"crashed-worker-{n}", stale)
            if job is not None:  # the worker "dies": its heartbeat goes stale
                await session.execute(
                    sa.text(
                        "UPDATE jobs SET heartbeat_at = now() - interval '1 hour' WHERE id = :id"
                    ),
                    {"id": job.id},
                )
            return job

    try:
        attempts = [job.attempts for n in range(1, 4) if (job := await crash_once(n))]
        assert attempts == [1, 2, 3]  # max_attempts = 3
        assert await crash_once(4) is None  # no fourth attempt, however stale the lock is

        worker, close = await build_worker(settings)
        try:
            await worker.tick()
        finally:
            await close()
    finally:
        await engine.dispose()

    job = await _job(settings, run_id)
    assert (job["status"], job["attempts"]) == ("failed", 3)
    assert "retry limit" in str(job["last_error"])
    run = (await client.get(f"{API}/runs/{run_id}")).json()
    assert run["status"] == "failed"
    assert run["error"]["type"] == "WorkerLost"
    assert (await _events(client, run_id))[-1]["type"] == "run.failed"


async def test_exhausted_job_does_not_override_a_cancelled_run(
    client: httpx.AsyncClient,
    settings: Settings,
) -> None:
    project_id = await create_project(client)
    run_id = (
        await client.post(f"{API}/projects/{project_id}/runs", json={"workflow": "dummy"})
    ).json()["id"]
    engine = make_engine(settings.database_url)
    try:
        async with session_scope(make_sessionmaker(engine)) as session:
            await session.execute(
                sa.text(
                    "UPDATE jobs SET status = 'running', attempts = max_attempts, "
                    "locked_by = 'gone', heartbeat_at = now() - interval '1 hour' "
                    "WHERE payload->>'run_id' = :r"
                ),
                {"r": run_id},
            )
    finally:
        await engine.dispose()
    assert (await client.post(f"{API}/runs/{run_id}/cancel")).status_code == 202
    worker, close = await build_worker(settings)
    try:
        await worker.tick()
    finally:
        await close()
    assert (await _job(settings, run_id))["status"] == "failed"
    assert (await client.get(f"{API}/runs/{run_id}")).json()["status"] == "cancelled"
