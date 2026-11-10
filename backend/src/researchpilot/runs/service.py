"""Run lifecycle: create, start, pause at checkpoints, decide, finish (ARCHITECTURE §4.3)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.core.errors import NotFound, ValidationFailed
from researchpilot.core.ids import uuid7
from researchpilot.domain.enums import CheckpointStatus, RunStatus, Workflow
from researchpilot.jobs.queue import enqueue
from researchpilot.runs.events import record_event

TERMINAL = {
    RunStatus.SUCCEEDED,
    RunStatus.PARTIALLY_SUCCEEDED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}


def _j(value: Any) -> str:
    return json.dumps(value, default=str)


async def create_run(
    session: AsyncSession,
    project_id: uuid.UUID,
    workflow: Workflow,
    config: dict[str, Any],
    manifest: dict[str, Any],
) -> uuid.UUID:
    run_id = uuid7()
    await session.execute(
        sa.text(
            "INSERT INTO research_runs (id, project_id, workflow, config, manifest) "
            "VALUES (:id, :p, :w, CAST(:c AS jsonb), CAST(:m AS jsonb))"
        ),
        {"id": run_id, "p": project_id, "w": workflow.value, "c": _j(config), "m": _j(manifest)},
    )
    await record_event(session, run_id, "run.queued", "Waiting to start")
    await enqueue(session, "run_workflow", {"run_id": str(run_id)})
    return run_id


async def mark_running(session: AsyncSession, run_id: uuid.UUID) -> None:
    await session.execute(
        sa.text(
            "UPDATE research_runs SET status = 'running', heartbeat_at = now(), "
            "started_at = coalesce(started_at, now()) WHERE id = :id"
        ),
        {"id": run_id},
    )


async def touch(session: AsyncSession, run_id: uuid.UUID) -> None:
    await session.execute(
        sa.text("UPDATE research_runs SET heartbeat_at = now() WHERE id = :id"), {"id": run_id}
    )


async def open_checkpoint(
    session: AsyncSession, run_id: uuid.UUID, name: str, payload: dict[str, Any]
) -> uuid.UUID:
    existing = (
        await session.execute(
            sa.text(
                "SELECT id FROM checkpoints WHERE run_id = :r AND name = :n AND status = 'pending'"
            ),
            {"r": run_id, "n": name},
        )
    ).scalar_one_or_none()
    checkpoint_id = existing or uuid7()
    if existing is None:
        await session.execute(
            sa.text(
                "INSERT INTO checkpoints (id, run_id, name, payload) "
                "VALUES (:id, :r, :n, CAST(:p AS jsonb))"
            ),
            {"id": checkpoint_id, "r": run_id, "n": name, "p": _j(payload)},
        )
    await session.execute(
        sa.text("UPDATE research_runs SET status = 'awaiting_approval' WHERE id = :id"),
        {"id": run_id},
    )
    await record_event(
        session,
        run_id,
        "checkpoint.opened",
        payload.get("question", "Your input is needed to continue"),
        data={"checkpoint_id": str(checkpoint_id), "name": name},
    )
    return checkpoint_id


async def decide_checkpoint(
    session: AsyncSession,
    checkpoint_id: uuid.UUID,
    status: CheckpointStatus,
    decision: dict[str, Any] | None,
    comment: str | None,
) -> uuid.UUID:
    if status is CheckpointStatus.PENDING:
        raise ValidationFailed("a decision must approve, modify or reject")
    row = (
        await session.execute(
            sa.text("SELECT c.run_id, c.status FROM checkpoints c WHERE c.id = :id FOR UPDATE"),
            {"id": checkpoint_id},
        )
    ).first()
    if row is None:
        raise NotFound("checkpoint not found")
    if row.status != CheckpointStatus.PENDING.value:
        raise ValidationFailed("this checkpoint has already been decided")
    await session.execute(
        sa.text(
            "UPDATE checkpoints SET status = :s, decision = CAST(:d AS jsonb), comment = :c, "
            "decided_at = now() WHERE id = :id"
        ),
        {"s": status.value, "d": _j(decision or {}), "c": comment, "id": checkpoint_id},
    )
    await session.execute(
        sa.text("UPDATE research_runs SET status = 'queued' WHERE id = :id"), {"id": row.run_id}
    )
    await record_event(
        session,
        row.run_id,
        "checkpoint.decided",
        "Thanks, continuing"
        if status is not CheckpointStatus.REJECTED
        else "Stopping as requested",
        data={"checkpoint_id": str(checkpoint_id), "status": status.value},
    )
    await enqueue(
        session,
        "resume_workflow",
        {
            "run_id": str(row.run_id),
            "resume": {"status": status.value, "decision": decision or {}, "comment": comment},
        },
    )
    return uuid.UUID(str(row.run_id))


async def finish(
    session: AsyncSession,
    run_id: uuid.UUID,
    status: RunStatus,
    message: str,
    error: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        sa.text(
            "UPDATE research_runs SET status = :s, finished_at = now(), "
            "error = CAST(:e AS jsonb) WHERE id = :id"
        ),
        {"s": status.value, "e": _j(error) if error else None, "id": run_id},
    )
    level = "error" if status is RunStatus.FAILED else "info"
    await record_event(
        session, run_id, f"run.{status.value}", message, level=level, data={"status": status.value}
    )


async def cancel(session: AsyncSession, run_id: uuid.UUID) -> None:
    status = (
        await session.execute(
            sa.text("SELECT status FROM research_runs WHERE id = :id FOR UPDATE"), {"id": run_id}
        )
    ).scalar_one()
    if RunStatus(status) in TERMINAL:
        raise ValidationFailed("the run has already finished")
    await session.execute(
        sa.text(
            "UPDATE jobs SET status = 'failed', last_error = 'cancelled', finished_at = now() "
            "WHERE status IN ('queued') AND payload->>'run_id' = :id"
        ),
        {"id": str(run_id)},
    )
    await finish(session, run_id, RunStatus.CANCELLED, "Cancelled")
