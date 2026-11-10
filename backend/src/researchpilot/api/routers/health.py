"""Liveness, readiness and dependency status (no secrets are ever returned)."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from researchpilot.api.errors import problem

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", response_model=None)
async def ready(request: Request) -> dict[str, str] | JSONResponse:
    try:
        async with request.app.state.sessions() as session:
            await session.execute(sa.text("SELECT 1"))
    except Exception:
        return problem(503, "dependency_unavailable", "Not ready", "database unreachable")
    return {"status": "ready"}


@router.get("/health/dependencies")
async def dependencies(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    llm = request.app.state.llm_manifest
    return {
        "database": "configured",
        "graph_backend": request.app.state.graph.backend,
        "llm": {
            "provisional": llm["provisional"],
            "providers": sorted({t["provider"] for t in llm["tasks"].values()}),
            "forced_fake": settings.llm_force_fake,
        },
        "integrations": {
            "anthropic": settings.anthropic_api_key is not None,
            "semantic_scholar": settings.s2_api_key is not None,
            "openalex": settings.openalex_api_key is not None,
            "github": settings.github_token is not None,
            "hugging_face": settings.hf_token is not None,
            "contact_email": settings.contact_email is not None,
        },
    }
