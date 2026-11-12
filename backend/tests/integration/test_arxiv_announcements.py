"""arXiv Announcement Capture: daily feed -> log -> primary announcement events (D31)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg
import pytest

from researchpilot.core.clock import FixedClock
from researchpilot.core.settings import Settings
from researchpilot.worker.main import ARXIV_CAPTURE_JOB, build_worker
from tests.fixtures.source_transport import FixtureTransport
from tests.integration.conftest import API, create_project

pytestmark = pytest.mark.integration


async def add(client: httpx.AsyncClient, project_id: str, identifier: str) -> str:
    resp = await client.post(f"{API}/projects/{project_id}/papers", json={"identifier": identifier})
    assert resp.status_code in (200, 201), resp.text
    return str(resp.json()["id"])


async def detail(client: httpx.AsyncClient, project_id: str, paper_id: str) -> dict[str, Any]:
    return dict((await client.get(f"{API}/projects/{project_id}/papers/{paper_id}")).json())


# The worker's own scheduling (``tick``) must not depend on the real date of the test run.
CLOCK = FixedClock(datetime(2026, 11, 11, 7, tzinfo=UTC))


async def run_capture(
    settings: Settings, transport: FixtureTransport, categories: list[str] | None = None
) -> None:
    worker_settings = settings.model_copy(
        update={"arxiv_capture_enabled": True, "arxiv_announcement_categories": categories or []}
    )
    worker, close = await build_worker(
        worker_settings, source_transport=transport, source_rate_limits=False, clock=CLOCK
    )
    try:
        assert await worker.schedule_periodic(datetime(2026, 11, 11, 7, tzinfo=UTC))
        while await worker.tick():
            pass
    finally:
        await close()


async def test_capture_turns_a_submission_only_date_into_a_verified_announcement(
    client: httpx.AsyncClient,
    settings: Settings,
    sources_transport: FixtureTransport,
    db: psycopg.Connection,
) -> None:
    """2611.13190: submitted 2026-11-09 20:10 UTC, announced in the 2026-11-11 feed (new).
    OpenAlex does not know it yet (recorded 404), so it starts as submission_only."""
    project_id = await create_project(client)
    paper_id = await add(client, project_id, "2611.13190")
    before = await detail(client, project_id, paper_id)
    assert before["resolved_date"]["basis"] == "submission_only"
    submission = next(e for e in before["dates"] if e["event"] == "preprint_submitted")

    await run_capture(settings, sources_transport)  # category comes from the project's paper

    after = await detail(client, project_id, paper_id)
    announced = next(e for e in after["dates"] if e["event"] == "preprint_announced")
    assert (announced["value"][:10], announced["precision"], announced["is_primary"]) == (
        "2026-11-11",
        "day",
        True,
    )
    assert (announced["reporting_source"], announced["upstream_source"]) == (
        "arxiv_announcement_feed",
        "arxiv",
    )
    assert announced["upstream_evidence"]["category"] == "q-bio.QM"
    r = after["resolved_date"]
    assert (r["confidence"], r["basis"], r["event_id"]) == (
        "verified",
        "announced",
        announced["id"],
    )
    # The submission event is unchanged and still listed.
    assert next(e for e in after["dates"] if e["event"] == "preprint_submitted") == submission
    log = db.execute(
        "SELECT announce_type, count(*) FROM arxiv_announcement_log "
        "WHERE category = 'q-bio.QM' GROUP BY 1 ORDER BY 1"
    ).fetchall()
    assert log == [("cross", 4), ("new", 3), ("replace", 2), ("replace-cross", 3)]


async def test_paper_added_after_the_capture_gets_its_announcement(
    client: httpx.AsyncClient,
    settings: Settings,
    sources_transport: FixtureTransport,
) -> None:
    await run_capture(settings, sources_transport, categories=["q-bio.QM"])
    project_id = await create_project(client)
    paper_id = await add(client, project_id, "2611.13190")
    d = await detail(client, project_id, paper_id)
    assert d["resolved_date"]["basis"] == "announced"
    assert d["resolved_date"]["first_public_appearance"].startswith("2026-11-11")


async def test_replacement_announces_the_version_not_the_work(
    client: httpx.AsyncClient,
    settings: Settings,
    sources_transport: FixtureTransport,
) -> None:
    """2604.22997 v2 'replace' on 2026-11-11: a version event, never the first appearance."""
    project_id = await create_project(client)
    paper_id = await add(client, project_id, "2604.22997")
    before = (await detail(client, project_id, paper_id))["resolved_date"]
    await run_capture(settings, sources_transport)
    d = await detail(client, project_id, paper_id)
    version = next(e for e in d["dates"] if e["event"] == "version_announced")
    assert (version["version"], version["value"][:10]) == (2, "2026-11-11")
    assert not any(e["event"] == "preprint_announced" for e in d["dates"])
    assert d["resolved_date"] == before  # the 2026-11-11 replacement does not make it new


async def test_capture_is_idempotent_and_runs_once_per_day(
    client: httpx.AsyncClient,
    settings: Settings,
    sources_transport: FixtureTransport,
    db: psycopg.Connection,
) -> None:
    project_id = await create_project(client)
    await add(client, project_id, "2611.13190")
    await run_capture(settings, sources_transport)
    counts = db.execute(
        "SELECT (SELECT count(*) FROM arxiv_announcement_log), (SELECT count(*) FROM paper_dates)"
    ).fetchone()
    worker_settings = settings.model_copy(update={"arxiv_capture_enabled": True})
    worker, close = await build_worker(
        worker_settings, source_transport=sources_transport, source_rate_limits=False, clock=CLOCK
    )
    try:
        assert not await worker.schedule_periodic(datetime(2026, 11, 11, 9, tzinfo=UTC))
        assert not await worker.schedule_periodic(datetime(2026, 11, 12, 3, tzinfo=UTC))
        from researchpilot.services.dates.announcements import capture

        await capture(worker._sessions, worker._sources.arxiv_feed, ["q-bio.QM"])  # type: ignore[union-attr]
    finally:
        await close()
    assert (
        db.execute(
            "SELECT (SELECT count(*) FROM arxiv_announcement_log), "
            "(SELECT count(*) FROM paper_dates)"
        ).fetchone()
        == counts
    )
    assert db.execute(
        "SELECT count(*) FROM jobs WHERE kind = %s", (ARXIV_CAPTURE_JOB,)
    ).fetchone() == (1,)


async def test_feed_failure_is_reported_and_logs_nothing(
    settings: Settings,
    sources_transport: FixtureTransport,
    db: psycopg.Connection,
) -> None:
    sources_transport.overrides["rss.arxiv.org"] = lambda r: httpx.Response(503)
    from researchpilot.services.dates.announcements import capture

    worker, close = await build_worker(
        settings, source_transport=sources_transport, source_rate_limits=False
    )
    try:
        report = await capture(
            worker._sessions,
            worker._sources.arxiv_feed,  # type: ignore[union-attr]
            ["q-bio.QM", "math.HO"],
        )
    finally:
        await close()
    assert report.categories == {"q-bio.QM": "error", "math.HO": "error"}
    assert db.execute("SELECT count(*) FROM arxiv_announcement_log").fetchone() == (0,)
