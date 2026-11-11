"""Integration fixtures: app, in-process HTTP client, worker factory and a live server."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx
import psycopg
import pytest
import uvicorn
from fastapi import FastAPI

from researchpilot.api.app import create_app
from researchpilot.core.settings import Settings
from researchpilot.worker.main import Worker, build_worker
from tests.conftest import _sqlalchemy_url
from tests.fixtures.source_transport import FixtureTransport

API = "/api/v1"


@pytest.fixture
def settings(migrated_db: str) -> Settings:
    return Settings(
        _env_file=None,
        database_url=_sqlalchemy_url(migrated_db),
        llm_force_fake=True,
        worker_poll_seconds=0.05,
        job_heartbeat_seconds=0.2,
        job_stale_after_seconds=1.0,
        log_json=True,
        log_level="WARNING",
    )


@pytest.fixture(autouse=True)
def _clean_global_paper_data(migrated_db: str) -> None:
    """Works, source records and caches are global (not project-scoped), so each test
    starts without them. DELETE (not TRUNCATE) so graph-node triggers fire."""
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute("DELETE FROM research_items WHERE item_type = 'paper'")
        conn.execute("DELETE FROM source_records")
        conn.execute("DELETE FROM http_cache")
        conn.execute("DELETE FROM source_rate_limits")


@pytest.fixture
def sources_transport() -> FixtureTransport:
    """Recorded scholarly-source responses; tests never call the real APIs."""
    return FixtureTransport()


@pytest.fixture
async def app(settings: Settings, sources_transport: FixtureTransport) -> AsyncIterator[FastAPI]:
    application = create_app(settings, source_transport=sources_transport, source_rate_limits=False)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


WorkerHandle = tuple[Worker, asyncio.Event, asyncio.Task[None]]


@pytest.fixture
async def start_worker(
    settings: Settings,
) -> AsyncIterator[Callable[[], Awaitable[WorkerHandle]]]:
    """Start workers on demand; every worker started is stopped (or cancelled) at teardown."""
    started: list[tuple[WorkerHandle, Callable[[], Awaitable[None]]]] = []

    async def start() -> WorkerHandle:
        worker, close = await build_worker(settings)
        stop = asyncio.Event()
        task = asyncio.create_task(worker.run_forever(stop))
        handle = (worker, stop, task)
        started.append((handle, close))
        return handle

    yield start
    for (_, stop, task), close in started:
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        await close()


@pytest.fixture
async def live_server(app: FastAPI) -> AsyncIterator[str]:
    """A real HTTP server (needed for streaming SSE end to end)."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_config=None, lifespan="off")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 - uvicorn exposes a flag, not an event
        await asyncio.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


async def create_project(client: httpx.AsyncClient, goal: str = "learn_field") -> str:
    resp = await client.post(
        f"{API}/projects",
        json={
            "topic": "graph neural networks for drug discovery",
            "expertise_level": "beginner",
            "goal": goal,
        },
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def wait_for_status(
    client: httpx.AsyncClient, run_id: str, wanted: set[str], limit_seconds: float = 15.0
) -> dict[str, object]:
    async with asyncio.timeout(limit_seconds):
        while True:
            run = (await client.get(f"{API}/runs/{run_id}")).json()
            if run["status"] in wanted:
                return dict(run)
            await asyncio.sleep(0.05)
