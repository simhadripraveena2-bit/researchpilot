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
            # The run records the objective version it uses; it never changes afterwards.
            "INSERT INTO research_runs (id, project_id, workflow, config, manifest, "
            "objective_version) VALUES (:id, :p, :w, CAST(:c AS jsonb), CAST(:m AS jsonb), "
            "(SELECT o.version FROM projects pr JOIN research_objectives o "
            "ON o.id = pr.active_objective_id WHERE pr.id = :p))"
        ),
        {"id": run_id, "p": project_id, "w": workflow.value, "c": _j(config), "m": _j(manifest)},
    )
    await record_event(session, run_id, "run.queued", "Waiting to start")
    await enqueue(session, "run_workflow", {"run_id": str(run_id)})
    return run_id


# Every status transition below is a *conditional* update ("... AND status NOT IN (terminal
# states)"): it only applies while the run is not finished. Once a run is terminal (e.g.
# cancelled), a worker that is still executing can no longer move it to another state - this
# closes the cancellation race.


class RunCancelled(Exception):
    # A control-flow signal, not an error.
    """Raised inside a workflow when its run was cancelled (cooperative cancellation)."""


async def mark_running(session: AsyncSession, run_id: uuid.UUID) -> bool:
    """Returns False if the run is already finished (nothing to execute)."""
    result = await session.execute(
        sa.text(
            "UPDATE research_runs SET status = 'running', heartbeat_at = now(), "
            "started_at = coalesce(started_at, now()) WHERE id = :id "
            "AND status NOT IN ('succeeded', 'partially_succeeded', 'failed', 'cancelled')"
        ),
        {"id": run_id},
    )
    return _changed(result)


async def is_cancelled(session: AsyncSession, run_id: uuid.UUID) -> bool:
    status = (
        await session.execute(
            sa.text("SELECT status FROM research_runs WHERE id = :id"), {"id": run_id}
        )
    ).scalar_one()
    return bool(status == RunStatus.CANCELLED.value)


async def touch(session: AsyncSession, run_id: uuid.UUID) -> None:
    await session.execute(
        sa.text("UPDATE research_runs SET heartbeat_at = now() WHERE id = :id"), {"id": run_id}
    )


async def open_checkpoint(
    session: AsyncSession, run_id: uuid.UUID, name: str, payload: dict[str, Any]
) -> uuid.UUID | None:
    """Pause the run for a human decision. Returns None if the run is already finished."""
    paused = await session.execute(
        sa.text(
            "UPDATE research_runs SET status = 'awaiting_approval' "
            "WHERE id = :id "
            "AND status NOT IN ('succeeded', 'partially_succeeded', 'failed', 'cancelled')"
        ),
        {"id": run_id},
    )
    if not _changed(paused):
        return None
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
            sa.text(
                "SELECT c.run_id, c.status, r.status AS run_status FROM checkpoints c "
                "JOIN research_runs r ON r.id = c.run_id WHERE c.id = :id FOR UPDATE"
            ),
            {"id": checkpoint_id},
        )
    ).first()
    if row is None:
        raise NotFound("checkpoint not found")
    if row.status != CheckpointStatus.PENDING.value:
        raise ValidationFailed("this checkpoint has already been decided")
    if RunStatus(row.run_status) in TERMINAL:
        raise ValidationFailed("the run has already finished")
    await session.execute(
        sa.text(
            "UPDATE checkpoints SET status = :s, decision = CAST(:d AS jsonb), comment = :c, "
            "decided_at = now() WHERE id = :id"
        ),
        {"s": status.value, "d": _j(decision or {}), "c": comment, "id": checkpoint_id},
    )
    await session.execute(
        sa.text(
            "UPDATE research_runs SET status = 'queued' WHERE id = :id "
            "AND status NOT IN ('succeeded', 'partially_succeeded', 'failed', 'cancelled')"
        ),
        {"id": row.run_id},
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
) -> bool:
    """Move the run to a terminal state. Returns False (and records nothing) if the run was
    already finished, e.g. cancelled while a worker was still executing it."""
    result = await session.execute(
        sa.text(
            "UPDATE research_runs SET status = :s, finished_at = now(), "
            "error = CAST(:e AS jsonb) WHERE id = :id "
            "AND status NOT IN ('succeeded', 'partially_succeeded', 'failed', 'cancelled')"
        ),
        {"s": status.value, "e": _j(error) if error else None, "id": run_id},
    )
    if not _changed(result):
        return False
    level = "error" if status is RunStatus.FAILED else "info"
    await record_event(
        session, run_id, f"run.{status.value}", message, level=level, data={"status": status.value}
    )
    return True


async def cancel(session: AsyncSession, run_id: uuid.UUID) -> None:
    """Cancel a run in any non-terminal state.

    Queued jobs are withdrawn and pending checkpoints closed. A job that is already running
    stops cooperatively (the workflow checks for cancellation at each progress event and
    step boundary, and the worker heartbeat interrupts it), and in any case can no longer
    change the run's state because every transition is conditional on the run not being
    finished.
    """
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
            "WHERE status = 'queued' AND payload->>'run_id' = :id"
        ),
        {"id": str(run_id)},
    )
    await session.execute(
        sa.text(
            "UPDATE checkpoints SET status = 'rejected', comment = 'run cancelled', "
            "decided_at = now() WHERE run_id = :id AND status = 'pending'"
        ),
        {"id": run_id},
    )
    await finish(session, run_id, RunStatus.CANCELLED, "Cancelled")


def _changed(result: Any) -> bool:
    return (getattr(result, "rowcount", 0) or 0) > 0
