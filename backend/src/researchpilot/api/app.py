"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute

from researchpilot import __version__
from researchpilot.api.errors import install_error_handlers
from researchpilot.api.routers import graph, health, projects, runs
from researchpilot.core.logging import configure_logging
from researchpilot.core.security import assert_safe_startup
from researchpilot.core.settings import Settings, get_settings
from researchpilot.db.session import make_engine, make_sessionmaker
from researchpilot.graph.adapters.postgres.service import PostgresGraphService
from researchpilot.llm.factory import runtime_llm_config
from researchpilot.worker.main import libpq_url

API_PREFIX = "/api/v1"
ROUTERS = (health.router, projects.router, runs.router, graph.router)


def iter_api_routes() -> list[tuple[str, APIRoute]]:
    """(full path, route) for every API route; used by the route-inventory test (R0-9)."""
    return [
        (API_PREFIX + route.path, route)
        for router in ROUTERS
        for route in router.routes
        if isinstance(route, APIRoute)
    ]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    assert_safe_startup(settings)  # also checked by the server entry point before binding

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level, settings.log_json, settings.secret_values())
        engine = make_engine(settings.database_url)
        app.state.settings = settings
        app.state.engine = engine
        app.state.sessions = make_sessionmaker(engine)
        app.state.libpq_url = libpq_url(settings.database_url)
        app.state.graph = PostgresGraphService(app.state.sessions)
        app.state.llm_manifest = runtime_llm_config(settings).manifest()
        try:
            yield
        finally:
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
