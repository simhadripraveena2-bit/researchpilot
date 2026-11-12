"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.routing import APIRoute

from researchpilot import __version__
from researchpilot.api.errors import install_error_handlers
from researchpilot.api.routers import (
    discovery,
    graph,
    health,
    objectives,
    papers,
    projects,
    releases,
    runs,
)
from researchpilot.core.clock import SystemClock
from researchpilot.core.logging import configure_logging
from researchpilot.core.security import assert_safe_startup
from researchpilot.core.settings import Settings, get_settings
from researchpilot.db.session import make_engine, make_sessionmaker
from researchpilot.graph.adapters.postgres.service import PostgresGraphService
from researchpilot.integrations.registry import build_sources
from researchpilot.llm.factory import runtime_llm_config
from researchpilot.worker.main import libpq_url

API_PREFIX = "/api/v1"
ROUTERS = (
    health.router,
    projects.router,
    papers.router,
    objectives.router,
    releases.router,
    runs.router,
    discovery.router,
    graph.router,
)


def iter_api_routes() -> list[tuple[str, APIRoute]]:
    """(full path, route) for every API route; used by the route-inventory test (R0-9)."""
    return [
        (API_PREFIX + route.path, route)
        for router in ROUTERS
        for route in router.routes
        if isinstance(route, APIRoute)
    ]


def create_app(
    settings: Settings | None = None,
    source_transport: httpx.AsyncBaseTransport | None = None,
    *,
    source_rate_limits: bool = True,
) -> FastAPI:
    """``source_transport`` replaces outbound HTTP to scholarly sources (recorded responses);
    ``source_rate_limits=False`` is only for tests that never reach a real source."""
    settings = settings or get_settings()
    assert_safe_startup(settings)  # also checked by the server entry point before binding

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level, settings.log_json, settings.secret_values())
        engine = make_engine(settings.database_url)
        app.state.settings = settings
        app.state.clock = SystemClock()  # replaceable in tests
        app.state.engine = engine
        app.state.sessions = make_sessionmaker(engine)
        app.state.libpq_url = libpq_url(settings.database_url)
        app.state.graph = PostgresGraphService(app.state.sessions)
        app.state.llm_manifest = runtime_llm_config(settings).manifest()
        app.state.sources = build_sources(
            settings, app.state.sessions, source_transport, rate_limits=source_rate_limits
        )
        try:
            yield
        finally:
            await app.state.sources.aclose()
            await engine.dispose()

    app = FastAPI(
        title="ResearchPilot",
        version=__version__,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
    )
    install_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router, prefix=API_PREFIX)
    return app
