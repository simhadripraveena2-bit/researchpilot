"""Postgres job queue: SKIP LOCKED claiming, heartbeats, retries and stale-lock recovery."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.core.ids import uuid7

NOTIFY_CHANNEL = "rp_jobs"


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


async def enqueue(
    session: AsyncSession, kind: str, payload: dict[str, Any], *, max_attempts: int = 3
) -> uuid.UUID:
    """Insert a job in the caller's transaction (it becomes visible on commit)."""
    job_id = uuid7()
    await session.execute(
        sa.text(
            "INSERT INTO jobs (id, kind, payload, max_attempts) "
            "VALUES (:id, :kind, CAST(:payload AS jsonb), :max_attempts)"
        ),
        {"id": job_id, "kind": kind, "payload": _json(payload), "max_attempts": max_attempts},
    )
    await session.execute(
        sa.text("SELECT pg_notify(:ch, :id)"), {"ch": NOTIFY_CHANNEL, "id": str(job_id)}
    )
    return job_id


async def claim(session: AsyncSession, worker_id: str, stale_after: timedelta) -> ClaimedJob | None:
    """Claim one runnable job: queued and due, or running with a stale heartbeat (its worker
    died). Reclaiming a stale job counts as a new attempt."""
    row = (
        await session.execute(
            sa.text(
                """
                UPDATE jobs SET status = 'running', locked_by = :worker, locked_at = now(),
                       heartbeat_at = now(), attempts = attempts + 1
                WHERE id = (
                    SELECT id FROM jobs
                    WHERE (status = 'queued' AND run_after <= now())
                       OR (status = 'running' AND heartbeat_at < now() - :stale)
                    ORDER BY run_after, created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING id, kind, payload, attempts, max_attempts
                """
            ),
            {"worker": worker_id, "stale": stale_after},
        )
    ).first()
    if row is None:
        return None
    return ClaimedJob(row.id, row.kind, dict(row.payload), row.attempts, row.max_attempts)


async def heartbeat(session: AsyncSession, job_id: uuid.UUID, worker_id: str) -> bool:
    """Returns False if the job was taken over (lock lost)."""
    result = await session.execute(
        sa.text(
            "UPDATE jobs SET heartbeat_at = now() WHERE id = :id AND locked_by = :worker "
            "AND status = 'running'"
        ),
        {"id": job_id, "worker": worker_id},
    )
    return (getattr(result, "rowcount", 0) or 0) == 1


async def complete(session: AsyncSession, job_id: uuid.UUID, worker_id: str) -> None:
    await session.execute(
        sa.text(
            "UPDATE jobs SET status = 'succeeded', finished_at = now(), last_error = NULL "
            "WHERE id = :id AND locked_by = :worker"
        ),
        {"id": job_id, "worker": worker_id},
    )


async def fail(session: AsyncSession, job: ClaimedJob, worker_id: str, error: str) -> bool:
    """Record a failure. Retries with exponential backoff; returns True if it was final."""
    final = job.attempts >= job.max_attempts
    await session.execute(
        sa.text(
            "UPDATE jobs SET status = :status, last_error = :error, locked_by = NULL, "
            "run_after = now() + make_interval(secs => :delay), "
            "finished_at = CASE WHEN :final THEN now() END "
            "WHERE id = :id AND locked_by = :worker"
        ),
        {
            "status": "failed" if final else "queued",
            "error": error[:4000],
            "final": final,
            "delay": min(2**job.attempts, 60),
            "id": job.id,
            "worker": worker_id,
        },
    )
    return final


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)
