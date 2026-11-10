"""Run progress events: stored in ``run_events`` and announced with NOTIFY (for SSE)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

NOTIFY_CHANNEL = "rp_run_events"


async def record_event(
    session: AsyncSession,
    run_id: uuid.UUID,
    type_: str,
    message: str,
    *,
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> int:
    event_id: int = (
        await session.execute(
            sa.text(
                "INSERT INTO run_events (run_id, type, message, level, data) "
                "VALUES (:run_id, :type, :message, :level, CAST(:data AS jsonb)) RETURNING id"
            ),
            {
                "run_id": run_id,
                "type": type_,
                "message": message,
                "level": level,
                "data": json.dumps(data or {}, default=str),
            },
        )
    ).scalar_one()
    # NOTIFY is transactional: listeners hear it only once the event is committed.
    await session.execute(
        sa.text("SELECT pg_notify(:ch, :payload)"),
        {"ch": NOTIFY_CHANNEL, "payload": f"{run_id}:{event_id}"},
    )
    return event_id
