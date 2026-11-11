"""arXiv Announcement Capture (ARCHITECTURE §4.8.5, D31): log -> date events -> resolution.

* ``capture()`` reads each category's daily feed and records every item in
  ``arxiv_announcement_log`` exactly as listed (category, ID, version, type, day).
* ``apply_announcements()`` turns log rows into date events for papers in the record - now,
  and whenever an arXiv paper is ingested later:
  ``new`` -> ``preprint_announced`` (the work's first announcement; primary, arXiv is the
  system of record) and ``replace`` -> ``version_announced`` for that version.
  ``cross`` / ``replace-cross`` stay in the log only: they can list old papers.
* Date-only values are stored at 00:00 UTC with day precision (D23); the announcement day is
  the feed's calendar date (US Eastern). Affected works are re-resolved.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.core.ids import uuid7
from researchpilot.domain.enums import DateEvent, DatePrecision, ReportingSource, UpstreamSource
from researchpilot.integrations.arxiv_feed import ArxivFeedClient
from researchpilot.integrations.base import SourceError
from researchpilot.services.dates.store import resolve_paper_dates
from researchpilot.services.papers.ingest import add_date

log = structlog.get_logger(__name__)

EVENT_FOR_TYPE = {"new": DateEvent.PREPRINT_ANNOUNCED, "replace": DateEvent.VERSION_ANNOUNCED}


@dataclass
class CaptureReport:
    categories: dict[str, str] = field(default_factory=dict)  # category -> ok / error
    logged: int = 0
    events_added: int = 0
    papers_updated: list[uuid.UUID] = field(default_factory=list)


async def categories_to_capture(session: AsyncSession, configured: list[str]) -> list[str]:
    """Configured categories plus the primary category of every arXiv work in a project
    (until M1c maps categories from research objectives)."""
    rows = await session.execute(
        sa.text(
            "SELECT DISTINCT p.fields_of_study[1] AS category FROM papers p "
            "JOIN project_items pi ON pi.item_id = p.id "
            "JOIN paper_manifestations m ON m.paper_id = p.id AND m.server_or_venue = 'arxiv' "
            "WHERE p.merged_into_id IS NULL AND cardinality(p.fields_of_study) > 0"
        )
    )
    found = {r.category for r in rows if r.category}
    return sorted(found | {c.strip() for c in configured if c.strip()})


async def capture(
    sessions: async_sessionmaker[AsyncSession], feeds: ArxivFeedClient, categories: list[str]
) -> CaptureReport:
    report = CaptureReport()
    for category in categories:
        try:
            snapshot = await feeds.fetch(category)
        except SourceError as exc:
            report.categories[category] = "error"
            log.warning("arxiv.capture_failed", category=category, detail=exc.detail)
            continue
        report.categories[category] = "ok"
        if snapshot.announcement_day is None:
            continue
        ids: list[str] = []
        async with sessions() as session, session.begin():
            for item in snapshot.items:
                inserted = (
                    await session.execute(
                        sa.text(
                            "INSERT INTO arxiv_announcement_log (id, category, arxiv_id, version, "
                            "announce_type, announcement_day, feed_fetched_at, source_record_id) "
                            "VALUES (:id, :c, :a, :v, :t, :d, :f, :r) "
                            "ON CONFLICT ON CONSTRAINT uq_arxiv_announcement_log_entry "
                            "DO NOTHING RETURNING id"
                        ),
                        {
                            "id": uuid7(),
                            "c": category,
                            "a": item.arxiv_id,
                            "v": item.version,
                            "t": item.announce_type,
                            "d": snapshot.announcement_day,
                            "f": snapshot.fetched_at,
                            "r": snapshot.source_record_id,
                        },
                    )
                ).scalar_one_or_none()
                report.logged += inserted is not None
                ids.append(item.arxiv_id)
            added, papers = await apply_announcements(session, ids)
        report.events_added += added
        report.papers_updated.extend(p for p in papers if p not in report.papers_updated)
    log.info(
        "arxiv.capture_done",
        categories=report.categories,
        logged=report.logged,
        events=report.events_added,
    )
    return report


async def apply_announcements(
    session: AsyncSession, arxiv_ids: list[str]
) -> tuple[int, list[uuid.UUID]]:
    """Adds announcement events for logged items whose paper is in the record."""
    if not arxiv_ids:
        return 0, []
    rows = (
        await session.execute(
            sa.text(
                "SELECT l.category, l.arxiv_id, l.version, l.announce_type, l.announcement_day, "
                "l.source_record_id, l.feed_fetched_at, i.paper_id, i.manifestation_id "
                "FROM arxiv_announcement_log l JOIN paper_identifiers i "
                "ON i.scheme = 'arxiv' AND i.value = l.arxiv_id "
                "WHERE l.arxiv_id = ANY(:ids) AND l.announce_type IN ('new', 'replace') "
                "ORDER BY l.announcement_day"
            ),
            {"ids": list(dict.fromkeys(arxiv_ids))},
        )
    ).all()
    added = 0
    papers: list[uuid.UUID] = []
    for r in rows:
        event = EVENT_FOR_TYPE[r.announce_type]
        day = datetime(
            r.announcement_day.year, r.announcement_day.month, r.announcement_day.day, tzinfo=UTC
        )
        before = await _count(session, r.manifestation_id)
        await add_date(
            session,
            r.paper_id,
            r.manifestation_id,
            event,
            day,
            DatePrecision.DAY,
            # "new" is the work's first announcement (v1 semantics even if replaced before
            # announcement); "replace" announces that version.
            version=None if event is DateEvent.PREPRINT_ANNOUNCED else r.version,
            is_primary=True,
            reporting=ReportingSource.ARXIV_ANNOUNCEMENT_FEED,
            upstream=UpstreamSource.ARXIV,
            evidence={
                "field": "item/pubDate",
                "category": r.category,
                "announce_type": r.announce_type,
                "listed_version": r.version,
                "meaning": "announcement day (US Eastern calendar date)",
            },
            record_id=r.source_record_id,
            retrieved_at=r.feed_fetched_at,
        )
        added += (await _count(session, r.manifestation_id)) - before
        if r.paper_id not in papers:
            papers.append(r.paper_id)
    now = datetime.now(UTC)
    for paper_id in papers:
        await resolve_paper_dates(session, paper_id, now)
    return added, papers


async def _count(session: AsyncSession, manifestation_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                sa.text("SELECT count(*) FROM paper_dates WHERE manifestation_id = :m"),
                {"m": manifestation_id},
            )
        ).scalar_one()
    )
