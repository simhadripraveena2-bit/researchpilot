"""Discovery (W1): start a run, see its plan, searches, sources, papers and summary.

All run endpoints are scoped through the run's project (404 for other users' runs). Every
response names the objective version the run used.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Request, status
from pydantic import BaseModel

from researchpilot.api.deps import ProjectScoped, RunScoped, Session
from researchpilot.api.schemas import Created
from researchpilot.core.errors import Forbidden, NotFound, ValidationFailed
from researchpilot.domain.enums import ProjectRole, Workflow
from researchpilot.services.discovery import summary
from researchpilot.services.discovery.planner import DiscoveryPlan, describe, plan
from researchpilot.services.discovery.runs import DiscoveryConfig, retry_discovery, start_discovery
from researchpilot.services.objectives.service import get_objective
from researchpilot.workflows.discovery import load_plan, run_row
from researchpilot.workflows.registry import WORKFLOWS

router = APIRouter(tags=["discovery"])


class DiscoveryStarted(Created):
    objective_version: int


class PlanOut(BaseModel):
    run_id: uuid.UUID | None
    objective_version: int
    description: str
    plan: DiscoveryPlan


def _editor(scope: Any) -> None:
    if scope.role is ProjectRole.VIEWER:
        raise Forbidden("viewers cannot start or retry discovery runs")


def manifest(request: Request) -> dict[str, Any]:
    spec = WORKFLOWS[Workflow.DISCOVERY]
    return {
        "code_version": request.app.state.settings.git_sha,
        "workflow": {"name": spec.name, "version": spec.version},
        "llm": request.app.state.llm_manifest,
    }


@router.post("/projects/{project_id}/discovery-runs", status_code=status.HTTP_202_ACCEPTED)
async def start(
    body: DiscoveryConfig, scope: ProjectScoped, session: Session, request: Request
) -> DiscoveryStarted:
    """Start discovery with the project's active objective version (422 without an
    objective, 409 while another discovery run is in progress)."""
    _editor(scope)
    run_id = await start_discovery(
        session,
        scope.project_id,
        body.model_dump(mode="json", exclude_none=True),
        manifest(request),
    )
    version = await session.scalar(
        sa.text("SELECT objective_version FROM research_runs WHERE id = :id"), {"id": run_id}
    )
    return DiscoveryStarted(id=run_id, objective_version=int(version))


@router.get("/projects/{project_id}/discovery/plan-preview")
async def plan_preview(scope: ProjectScoped, session: Session) -> PlanOut:
    """The plan the active objective version would produce (nothing is run or stored)."""
    objective = await get_objective(session, scope.project_id)
    the_plan = plan(objective.id, objective.version, objective.content())
    return PlanOut(
        run_id=None,
        objective_version=objective.version,
        description=describe(the_plan),
        plan=the_plan,
    )


async def _discovery_run(session: Session, run_id: uuid.UUID) -> tuple[Any, DiscoveryPlan]:
    row = await run_row(session, run_id)
    workflow = await session.scalar(
        sa.text("SELECT workflow FROM research_runs WHERE id = :id"), {"id": run_id}
    )
    if workflow != Workflow.DISCOVERY.value:
        raise NotFound("not a discovery run")
    the_plan = await load_plan(session, run_id)
    if the_plan is None:
        raise ValidationFailed("the run has not prepared its plan yet")
    return row, the_plan


@router.get("/runs/{run_id}/discovery/plan")
async def run_plan(run_id: uuid.UUID, scope: RunScoped, session: Session) -> PlanOut:
    _, the_plan = await _discovery_run(session, run_id)
    return PlanOut(
        run_id=run_id,
        objective_version=the_plan.objective_version,
        description=describe(the_plan),
        plan=the_plan,
    )


@router.get("/runs/{run_id}/discovery/searches")
async def run_searches(run_id: uuid.UUID, scope: RunScoped, session: Session) -> dict[str, Any]:
    """Every query sent (or not): source, text, time, status, counts, cache, error."""
    _, the_plan = await _discovery_run(session, run_id)
    return {
        "objective_version": the_plan.objective_version,
        "searches": await summary.search_history(session, run_id),
    }


@router.get("/runs/{run_id}/discovery/sources")
async def run_sources(run_id: uuid.UUID, scope: RunScoped, session: Session) -> dict[str, Any]:
    """Per source: searches that succeeded, failed, ran out of budget or were skipped."""
    _, the_plan = await _discovery_run(session, run_id)
    return {
        "objective_version": the_plan.objective_version,
        "sources": await summary.source_report(session, run_id),
        "not_searched": [c.model_dump() for c in the_plan.sources if not c.used],
    }


@router.get("/runs/{run_id}/discovery/papers")
async def run_papers(run_id: uuid.UUID, scope: RunScoped, session: Session) -> dict[str, Any]:
    row, the_plan = await _discovery_run(session, run_id)
    window = int((row.config or {}).get("release_window_days", 30))
    return {
        "objective_version": the_plan.objective_version,
        "release_window_days": window,
        "papers": await summary.discovered_papers(
            session, run_id, the_plan, datetime.now(UTC), window
        ),
    }


@router.get("/runs/{run_id}/discovery/summary")
async def run_summary(run_id: uuid.UUID, scope: RunScoped, session: Session) -> dict[str, Any]:
    """Recomputed from the stored log (current dates, merges and release types)."""
    row, the_plan = await _discovery_run(session, run_id)
    run_status = await session.scalar(
        sa.text("SELECT status FROM research_runs WHERE id = :id"), {"id": run_id}
    )
    discovery = (row.manifest or {}).get("discovery", {})
    window = int((row.config or {}).get("release_window_days", 30))
    result = await summary.build_summary(
        session, run_id, the_plan, datetime.now(UTC), discovery.get("citations"), window
    )
    return {"run_id": str(run_id), "status": run_status, **result}


@router.post("/runs/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry(run_id: uuid.UUID, scope: RunScoped, session: Session) -> dict[str, str]:
    """Retry a failed or partial discovery run: only what failed is done again."""
    _editor(scope)
    await retry_discovery(session, run_id)
    return {"status": "queued"}
