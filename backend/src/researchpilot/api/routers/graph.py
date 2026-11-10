"""Graph exploration endpoints, always project-scoped (ARCHITECTURE §12.8)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request

from researchpilot.api.deps import ProjectScoped
from researchpilot.graph.service import GraphScope
from researchpilot.graph.view import AssertionPolicy, GraphView

router = APIRouter(tags=["graph"])


@router.get("/projects/{project_id}/graph/nodes/{uid}/neighbors")
async def neighbors(
    uid: uuid.UUID,
    scope: ProjectScoped,
    request: Request,
    assertion_policy: AssertionPolicy = AssertionPolicy.ESTABLISHED_ONLY,
) -> GraphView:
    view: GraphView = await request.app.state.graph.neighbors(
        uid, GraphScope(scope.project_id), assertion_policy
    )
    return view


@router.get("/projects/{project_id}/graph/paths")
async def paths(
    scope: ProjectScoped,
    request: Request,
    source: Annotated[uuid.UUID, Query()],
    target: Annotated[uuid.UUID, Query()],
    max_hops: Annotated[int, Query(ge=1, le=6)] = 3,
    assertion_policy: AssertionPolicy = AssertionPolicy.ESTABLISHED_ONLY,
) -> list[GraphView]:
    views: list[GraphView] = await request.app.state.graph.paths(
        source, target, GraphScope(scope.project_id), assertion_policy, max_hops
    )
    return views
