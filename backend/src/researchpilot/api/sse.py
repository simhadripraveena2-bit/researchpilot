"""Server-Sent Events for run progress (ARCHITECTURE §4.3).

A client receives every stored event after ``Last-Event-ID`` (so reconnects lose nothing),
then live events signalled by Postgres NOTIFY. A periodic poll is the safety net if a
notification is missed, and a comment line keeps idle connections alive. The stream ends
once the run reaches a terminal state and all its events have been sent.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator

import psycopg
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.domain.enums import RunStatus
from researchpilot.runs.events import NOTIFY_CHANNEL
from researchpilot.runs.service import TERMINAL


def format_sse(event_id: int, event: str, data: dict[str, object]) -> str:
    payload = json.dumps(data, default=str, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event}\ndata: {payload}\n\n"


async def run_event_stream(
    run_id: uuid.UUID,
    after_id: int,
    sessions: async_sessionmaker[AsyncSession],
    libpq_url: str,
    *,
    keepalive_seconds: float = 15.0,
    poll_seconds: float = 2.0,
) -> AsyncIterator[str]:
    last_id = after_id
    async with await psycopg.AsyncConnection.connect(libpq_url, autocommit=True) as listener:
        await listener.execute(f"LISTEN {NOTIFY_CHANNEL}")
        idle = 0.0
        while True:
            async with sessions() as session:
                rows = (
                    await session.execute(
                        sa.text(
                            "SELECT id, ts, level, type, message, data FROM run_events "
                            "WHERE run_id = :r AND id > :after ORDER BY id"
                        ),
                        {"r": run_id, "after": last_id},
                    )
                ).all()
                status = (
                    await session.execute(
                        sa.text("SELECT status FROM research_runs WHERE id = :r"), {"r": run_id}
                    )
                ).scalar_one()
            for row in rows:
                last_id = row.id
                yield format_sse(
                    row.id,
                    "run_event",
                    {
                        "id": row.id,
                        "ts": row.ts.isoformat(),
                        "level": row.level,
                        "type": row.type,
                        "message": row.message,
                        "data": row.data,
                    },
                )
            if RunStatus(status) in TERMINAL:
                return
            if rows:
                idle = 0.0
            got_notice = await _wait_for_notice(listener, run_id, poll_seconds)
            idle = 0.0 if got_notice else idle + poll_seconds
            if idle >= keepalive_seconds:
                idle = 0.0
                yield ": keep-alive\n\n"


async def _wait_for_notice(
    conn: psycopg.AsyncConnection, run_id: uuid.UUID, wait_seconds: float
) -> bool:
    prefix = f"{run_id}:"
    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(wait_seconds):
            async for notice in conn.notifies():
                if notice.payload.startswith(prefix):
                    return True
    return False
