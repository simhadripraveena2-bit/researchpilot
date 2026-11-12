"""Runs, progress events (SSE) and checkpoints."""

from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Header, Request, status
from fastapi.responses import StreamingResponse

from researchpilot.api.deps import CheckpointScoped, ProjectScoped, RunScoped, Session
from researchpilot.api.schemas import (
    CheckpointDecision,
    CheckpointOut,
    Created,
    RunCreate,
    RunEventOut,
    RunOut,
)
from researchpilot.api.sse import run_event_stream
from researchpilot.core.errors import Forbidden, ValidationFailed
from researchpilot.domain.enums import ProjectRole, Workflow
from researchpilot.runs import service
from researchpilot.workflows.registry import WORKFLOWS

router = APIRouter(tags=["runs"])

_RUN = (
    "id, project_id, workflow, status, config, manifest, error, objective_version, created_at, "
    "started_at, finished_at"
)
_CHECKPOINT = "id, run_id, name, payload, status, decision, comment, created_at, decided_at"


@router.post("/projects/{project_id}/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    body: RunCreate, scope: ProjectScoped, session: Session, request: Request
) -> Created:
    if scope.role is ProjectRole.VIEWER:
        raise Forbidden("viewers cannot start runs")
    if body.workflow not in WORKFLOWS:
        raise ValidationFailed(f"workflow {body.workflow.value!r} is not available yet")
    spec = WORKFLOWS[Workflow(body.workflow)]
    manifest = {
        "code_version": request.app.state.settings.git_sha,
        "workflow": {"name": spec.name, "version": spec.version},
        "llm": request.app.state.llm_manifest,
    }
    run_id = await service.create_run(
        session, scope.project_id, body.workflow, body.config, manifest
    )
    return Created(id=run_id)


@router.get("/projects/{project_id}/runs")
async def list_runs(scope: ProjectScoped, session: Session) -> list[RunOut]:
    rows = (
        (
            await session.execute(
                sa.text(
                    f"SELECT {_RUN} FROM research_runs "  # noqa: S608 - constant column list
                    "WHERE project_id = :p ORDER BY created_at DESC"
                ),
                {"p": scope.project_id},
            )
        )
        .mappings()
        .all()
    )
    return [RunOut.model_validate(dict(r)) for r in rows]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, scope: RunScoped, session: Session) -> RunOut:
    row = (
        (
            await session.execute(
                sa.text(f"SELECT {_RUN} FROM research_runs WHERE id = :id"),  # noqa: S608
                {"id": run_id},
            )
        )
        .mappings()
        .one()
    )
    return RunOut.model_validate(dict(row))


@router.post("/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(run_id: str, scope: RunScoped, session: Session) -> dict[str, str]:
    if scope.role is ProjectRole.VIEWER:
        raise Forbidden("viewers cannot cancel runs")
    import uuid

    await service.cancel(session, uuid.UUID(run_id))
    return {"status": "cancelled"}


@router.get("/runs/{run_id}/events/log")
async def event_log(
    run_id: str, scope: RunScoped, session: Session, after: int = 0
) -> list[RunEventOut]:
    rows = (
        (
            await session.execute(
                sa.text(
                    "SELECT id, ts, level, type, message, data FROM run_events WHERE run_id = :r "
                    "AND id > :after ORDER BY id LIMIT 500"
                ),
                {"r": run_id, "after": after},
            )
        )
        .mappings()
        .all()
    )
    return [RunEventOut.model_validate(dict(r)) for r in rows]


@router.get("/runs/{run_id}/events")
async def event_stream(
    run_id: str,
    scope: RunScoped,
    request: Request,
    last_event_id: int | None = Header(default=None),
) -> StreamingResponse:
    import uuid

    state = request.app.state
    stream = run_event_stream(
        uuid.UUID(run_id), last_event_id or 0, state.sessions, state.libpq_url
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}/checkpoints")
async def list_checkpoints(run_id: str, scope: RunScoped, session: Session) -> list[CheckpointOut]:
    rows = (
        (
            await session.execute(
                sa.text(
                    f"SELECT {_CHECKPOINT} FROM checkpoints WHERE run_id = :r "  # noqa: S608
                    "ORDER BY (status = 'pending') DESC, created_at"
                ),
                {"r": run_id},
            )
        )
        .mappings()
        .all()
    )
    return [CheckpointOut.model_validate(dict(r)) for r in rows]


@router.post("/checkpoints/{checkpoint_id}/decision", status_code=status.HTTP_202_ACCEPTED)
async def decide(
    checkpoint_id: str, body: CheckpointDecision, scope: CheckpointScoped, session: Session
) -> dict[str, str]:
    if scope.role is ProjectRole.VIEWER:
        raise Forbidden("viewers cannot decide checkpoints")
    import uuid

    await service.decide_checkpoint(
        session, uuid.UUID(checkpoint_id), body.status, body.decision, body.comment
    )
    return {"status": "accepted"}
