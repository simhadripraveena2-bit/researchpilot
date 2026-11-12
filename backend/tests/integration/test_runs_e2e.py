"""R0-3 and R0-8: a run streams events over SSE, pauses at a checkpoint, survives worker
restarts (including a crash mid-step), resumes after approval, and records its provider."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable

import httpx
import pytest

from tests.integration.conftest import API, WorkerHandle, create_project, wait_for_status

pytestmark = pytest.mark.integration


async def _read_sse(
    base: str,
    run_id: str,
    until: Callable[[dict[str, object]], bool],
    last_event_id: int = 0,
    limit_seconds: float = 15.0,
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    headers = {"Last-Event-ID": str(last_event_id)} if last_event_id else {}
    async with (
        httpx.AsyncClient(base_url=base, timeout=limit_seconds) as c,
        c.stream("GET", f"{API}/runs/{run_id}/events", headers=headers) as resp,
    ):
        assert resp.headers["content-type"].startswith("text/event-stream")
        async with asyncio.timeout(limit_seconds):
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[len("data: ") :])
                    events.append(event)
                    if until(event):
                        break
    return events


async def _stop(handle: WorkerHandle, *, crash: bool = False) -> None:
    _, stop, task = handle
    if crash:
        task.cancel()  # simulates the process dying mid-step: no clean shutdown
    else:
        stop.set()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_run_streams_pauses_survives_restart_and_resumes(
    client: httpx.AsyncClient,
    live_server: str,
    start_worker: Callable[[], Awaitable[WorkerHandle]],
) -> None:
    project_id = await create_project(client)
    run_id = (
        await client.post(f"{API}/projects/{project_id}/runs", json={"workflow": "dummy"})
    ).json()["id"]
    first = await start_worker()

    # Live progress over SSE until the checkpoint opens.
    events = await _read_sse(live_server, run_id, lambda e: e["type"] == "checkpoint.opened")
    types = [e["type"] for e in events]
    assert types[:3] == ["run.queued", "run.started", "step.started"]
    assert "step.completed" in types
    assert all(isinstance(e["message"], str) and e["message"] for e in events)
    await wait_for_status(client, run_id, {"awaiting_approval"})

    # The worker goes away while the run waits; a new worker takes over.
    await _stop(first)
    await start_worker()
    checkpoint = (await client.get(f"{API}/runs/{run_id}/checkpoints")).json()[0]
    assert checkpoint["status"] == "pending" and checkpoint["name"] == "approve_test_run"
    decided = await client.post(
        f"{API}/checkpoints/{checkpoint['id']}/decision", json={"status": "approved"}
    )
    assert decided.status_code == 202

    # Reconnecting with Last-Event-ID only delivers new events, through to the end.
    rest = await _read_sse(
        live_server,
        run_id,
        lambda e: e["type"] == "run.succeeded",
        last_event_id=int(events[-1]["id"]),
    )
    assert rest[0]["id"] > events[-1]["id"]
    assert rest[-1]["type"] == "run.succeeded"
    run = await wait_for_status(client, run_id, {"succeeded"})

    # R0-8: the manifest records the provider that actually ran, flagged provisional.
    llm = run["manifest"]["llm"]  # type: ignore[index]
    assert llm["provisional"] is True
    assert llm["tasks"]["dummy_echo"]["provider"] == "fake"
    completed = next(e for e in events if e["type"] == "step.completed")
    assert completed["data"] == {"provider": "fake", "provisional": True}

    # A decided checkpoint cannot be decided again.
    again = await client.post(
        f"{API}/checkpoints/{checkpoint['id']}/decision", json={"status": "approved"}
    )
    assert again.status_code == 422


async def test_worker_crash_mid_step_is_recovered_not_left_running(
    client: httpx.AsyncClient,
    start_worker: Callable[[], Awaitable[WorkerHandle]],
) -> None:
    project_id = await create_project(client)
    run_id = (
        await client.post(
            f"{API}/projects/{project_id}/runs",
            json={"workflow": "dummy", "config": {"pause_seconds": 1.5}},
        )
    ).json()["id"]
    crashed = await start_worker()
    await wait_for_status(client, run_id, {"running"})
    await asyncio.sleep(0.3)  # inside the 'prepare' step
    await _stop(crashed, crash=True)

    await start_worker()  # reclaims the job once its heartbeat is stale (1 s in tests)
    await wait_for_status(client, run_id, {"awaiting_approval"}, limit_seconds=20)
    log = (await client.get(f"{API}/runs/{run_id}/events/log")).json()
    assert "run.resumed" in [e["type"] for e in log]


async def test_rejecting_the_checkpoint_stops_the_run(
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
    await client.post(
        f"{API}/checkpoints/{checkpoint['id']}/decision",
        json={"status": "rejected", "comment": "not now"},
    )
    run = await wait_for_status(client, run_id, {"cancelled"})
    assert run["finished_at"] is not None


async def test_unavailable_workflow_is_rejected(client: httpx.AsyncClient) -> None:
    project_id = await create_project(client)
    resp = await client.post(f"{API}/projects/{project_id}/runs", json={"workflow": "assessment"})
    assert resp.status_code == 422
    assert "not available yet" in resp.json()["detail"]
