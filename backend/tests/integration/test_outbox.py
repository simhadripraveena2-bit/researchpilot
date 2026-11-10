"""R0-4: outbox events exist only if committed; failing consumers are retried idempotently."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.core.settings import Settings
from researchpilot.db.session import make_engine, make_sessionmaker, session_scope
from researchpilot.events.outbox import Dispatcher, Event, emit

pytestmark = pytest.mark.integration


async def test_rolled_back_event_is_never_dispatched_and_retries_are_idempotent(
    settings: Settings,
) -> None:
    engine = make_engine(settings.database_url)
    sessions = make_sessionmaker(engine)
    calls: dict[str, int] = {"good": 0, "flaky": 0}
    fail_flaky = {"remaining": 2}

    async def good(_: AsyncSession, event: Event) -> None:
        if event.type == "test.outbox":
            calls["good"] += 1

    async def flaky(_: AsyncSession, event: Event) -> None:
        if event.type == "test.outbox":
            calls["flaky"] += 1
            if fail_flaky["remaining"]:
                fail_flaky["remaining"] -= 1
                raise RuntimeError("temporary failure")

    dispatcher = Dispatcher(sessions)
    dispatcher.register("test.outbox", "good", good)
    dispatcher.register("test.outbox", "flaky", flaky)
    try:
        # Rolled back: the event must never exist.
        async with sessions() as session:
            async with session.begin():
                await emit(session, "test.outbox", payload={"n": "rolled-back"})
                await session.rollback()
        async with session_scope(sessions) as session:
            await emit(session, "test.outbox", payload={"n": "committed"})

        for _ in range(5):
            await dispatcher.dispatch_once()

        async with session_scope(sessions) as session:
            rows = (
                await session.execute(
                    sa.text(
                        "SELECT payload->>'n' AS n, attempts, processed_at IS NOT NULL AS done "
                        "FROM domain_events WHERE type = 'test.outbox'"
                    )
                )
            ).all()
            delivered = {
                r[0]
                for r in await session.execute(
                    sa.text(
                        "SELECT d.consumer FROM domain_event_deliveries d JOIN domain_events e "
                        "ON e.id = d.event_id WHERE e.type = 'test.outbox'"
                    )
                )
            }
        assert [(r.n, r.attempts, r.done) for r in rows] == [("committed", 2, True)]
        assert calls == {"good": 1, "flaky": 3}  # 'good' never re-ran during flaky's retries
        assert delivered == {"good", "flaky"}
    finally:
        await engine.dispose()
