"""Transactional outbox and idempotent dispatcher (ARCHITECTURE §4.4, R0-4).

* ``emit`` writes a ``domain_events`` row in the caller's transaction, so an event exists only
  if the change that produced it was committed.
* ``Dispatcher.dispatch_once`` delivers pending events to their consumers. Each successful
  delivery is recorded per consumer, so a retry never re-runs a consumer that already
  succeeded. Consumers must also be idempotent themselves (deliveries are at-least-once).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.core.logging import get_logger


@dataclass(frozen=True)
class Event:
    id: int
    type: str
    item_id: uuid.UUID | None
    project_id: uuid.UUID | None
    payload: dict[str, Any]


Handler = Callable[[AsyncSession, Event], Awaitable[None]]


async def emit(
    session: AsyncSession,
    type_: str,
    *,
    project_id: uuid.UUID | None = None,
    item_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    import json

    await session.execute(
        sa.text(
            "INSERT INTO domain_events (type, project_id, item_id, payload) "
            "VALUES (:type, :project_id, :item_id, CAST(:payload AS jsonb))"
        ),
        {
            "type": type_,
            "project_id": project_id,
            "item_id": item_id,
            "payload": json.dumps(payload or {}, default=str),
        },
    )


class Dispatcher:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], max_attempts: int = 10) -> None:
        self._sessions = sessions
        self._consumers: dict[str, list[tuple[str, Handler]]] = defaultdict(list)
        self._max_attempts = max_attempts
        self._log = get_logger(component="outbox")

    def register(self, event_type: str, consumer: str, handler: Handler) -> None:
        self._consumers[event_type].append((consumer, handler))

    async def dispatch_once(self, batch: int = 50) -> int:
        """Process up to ``batch`` pending events. Returns how many were completed."""
        completed = 0
        async with self._sessions() as session, session.begin():
            rows = (
                await session.execute(
                    sa.text(
                        "SELECT id, type, item_id, project_id, payload FROM domain_events "
                        "WHERE processed_at IS NULL AND attempts < :max ORDER BY id "
                        "FOR UPDATE SKIP LOCKED LIMIT :batch"
                    ),
                    {"max": self._max_attempts, "batch": batch},
                )
            ).all()
            for row in rows:
                event = Event(row.id, row.type, row.item_id, row.project_id, dict(row.payload))
                if await self._deliver(session, event):
                    completed += 1
        return completed

    async def _deliver(self, session: AsyncSession, event: Event) -> bool:
        done = {
            r[0]
            for r in await session.execute(
                sa.text("SELECT consumer FROM domain_event_deliveries WHERE event_id = :id"),
                {"id": event.id},
            )
        }
        errors: list[str] = []
        for consumer, handler in self._consumers.get(event.type, []):
            if consumer in done:
                continue
            try:
                async with session.begin_nested():
                    await handler(session, event)
                    await session.execute(
                        sa.text(
                            "INSERT INTO domain_event_deliveries (event_id, consumer) "
                            "VALUES (:id, :consumer)"
                        ),
                        {"id": event.id, "consumer": consumer},
                    )
            except Exception as exc:
                errors.append(f"{consumer}: {exc}")
                self._log.warning(
                    "outbox.consumer_failed",
                    event_id=event.id,
                    event_type=event.type,
                    consumer=consumer,
                    error=str(exc),
                )
        if errors:
            await session.execute(
                sa.text(
                    "UPDATE domain_events SET attempts = attempts + 1, last_error = :err "
                    "WHERE id = :id"
                ),
                {"id": event.id, "err": "; ".join(errors)[:4000]},
            )
            return False
        await session.execute(
            sa.text("UPDATE domain_events SET processed_at = now() WHERE id = :id"),
            {"id": event.id},
        )
        return True
