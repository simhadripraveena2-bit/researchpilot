"""arXiv daily announcement feeds (rss.arxiv.org/rss/{category}; ARCHITECTURE §4.8.5).

Verified field semantics (2026-11-11; see docs/integrations/ARXIV.md):

* One RSS 2.0 feed per category, rebuilt once per announcement (``lastBuildDate`` ~05:00
  UTC); ``skipDays`` Saturday and Sunday; no history - only the latest announcement day.
* Channel and item ``pubDate`` are the **announcement day at midnight US Eastern**
  (``Wed, 11 Nov 2026 00:00:00 -0500``); the calendar date is the announcement day.
* Item ``arxiv:announce_type`` is one of ``new``, ``cross``, ``replace``, ``replace-cross``;
  ``guid`` is ``oai:arXiv.org:<id>v<version>``.
* ``cross`` and ``replace-cross`` items can be **old papers** cross-listed later
  (``2109.05627v2`` listed as ``cross`` on 2026-11-11), so they are not announcement dates.
* A category can have an empty feed on an announcement day (``math.HO``: 0 items).
* ``ETag`` and ``Cache-Control: max-age`` ~ 24 h are sent.

Only what the feed shows is recorded; arXiv's request rules apply (shared budget with the
arXiv API).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

import defusedxml.ElementTree as SafeET

from researchpilot.domain.enums import SourceName
from researchpilot.domain.identifiers import InvalidIdentifier, normalize_arxiv
from researchpilot.integrations.base import (
    SourceClient,
    SourceError,
    SourcePolicy,
    SourceRecordStore,
)

FEED_URL = "https://rss.arxiv.org/rss/{category}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
ANNOUNCE_TYPES = frozenset({"new", "cross", "replace", "replace-cross"})

FEED_POLICY = SourcePolicy(
    source=SourceName.ARXIV_ANNOUNCEMENT_FEED,
    min_interval_seconds=3.0,
    rate_limit_key=SourceName.ARXIV_API,  # one budget for everything arXiv serves
    cache_ttl={"feed": timedelta(hours=1)},
)


@dataclass(frozen=True)
class Announcement:
    arxiv_id: str
    version: int | None
    announce_type: str
    categories: tuple[str, ...]


@dataclass(frozen=True)
class FeedSnapshot:
    category: str
    announcement_day: date | None  # None if the feed carries no pubDate
    items: tuple[Announcement, ...]
    source_record_id: uuid.UUID
    fetched_at: datetime


class ArxivFeedClient:
    def __init__(self, client: SourceClient, records: SourceRecordStore) -> None:
        if client.source is not SourceName.ARXIV_ANNOUNCEMENT_FEED:
            raise ValueError("ArxivFeedClient needs an arxiv_announcement_feed SourceClient")
        self._client = client
        self._records = records

    async def fetch(self, category: str) -> FeedSnapshot:
        response = await self._client.get(FEED_URL.format(category=category), endpoint_class="feed")
        day, items = parse_feed(response.text)
        record_id = await self._records.save(
            SourceName.ARXIV_ANNOUNCEMENT_FEED,
            f"{category}:{day.isoformat() if day else 'unknown'}",
            "rss",
            {"category": category, "rss": response.text},
            response.fetched_at,
        )
        return FeedSnapshot(category, day, tuple(items), record_id, response.fetched_at)


def announcement_day(pub_date: str | None) -> date | None:
    """The calendar date of an RSS pubDate in its own offset (US Eastern midnight)."""
    if not pub_date:
        return None
    try:
        return parsedate_to_datetime(pub_date).date()
    except (TypeError, ValueError):
        return None


def parse_feed(xml_text: str) -> tuple[date | None, list[Announcement]]:
    try:
        root = SafeET.fromstring(xml_text)
    except SafeET.ParseError as exc:
        raise SourceError(SourceName.ARXIV_ANNOUNCEMENT_FEED, "arXiv feed is not XML") from exc
    channel = root.find("channel")
    if channel is None:
        raise SourceError(SourceName.ARXIV_ANNOUNCEMENT_FEED, "arXiv feed without a channel")
    day = announcement_day(channel.findtext("pubDate"))
    items: list[Announcement] = []
    for item in channel.findall("item"):
        announce_type = (item.findtext(f"{ARXIV_NS}announce_type") or "").strip()
        guid = (item.findtext("guid") or "").strip()
        if announce_type not in ANNOUNCE_TYPES or not guid:
            continue
        item_day = announcement_day(item.findtext("pubDate"))
        if day is not None and item_day is not None and item_day != day:
            raise SourceError(
                SourceName.ARXIV_ANNOUNCEMENT_FEED,
                "arXiv feed items disagree on the announcement day",
            )
        try:
            arxiv_id, version = normalize_arxiv(guid.rsplit(":", 1)[-1])
        except InvalidIdentifier:
            continue
        items.append(
            Announcement(
                arxiv_id,
                version,
                announce_type,
                tuple(c.text or "" for c in item.findall("category") if c.text),
            )
        )
    return day, items
