"""Crossref parsing and client behaviour against recorded responses (recorded 2026-11-11)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from researchpilot.domain.enums import DatePrecision, SourceName
from researchpilot.integrations.base import (
    InProcessRateLimiter,
    MemoryHttpCache,
    SourceClient,
    SourceNotFound,
)
from researchpilot.integrations.crossref import (
    CROSSREF_POLICY,
    CrossrefClient,
    clean_markup,
    parse_date,
    parse_work,
)
from researchpilot.services.papers.ingest_crossref import classify
from tests.fixtures.source_transport import SOURCES, FixtureTransport
from tests.unit.test_source_client import FakeTime

CROSSREF = SOURCES / "crossref"


def work(doi: str):  # type: ignore[no-untyped-def]
    path = CROSSREF / ("works_" + quote(doi, safe="") + ".json")
    return parse_work(json.loads(Path(path).read_text())["message"])


def test_journal_article_dates_and_preprint_relation() -> None:
    elife = work("10.7554/elife.87434")
    assert elife.type == "journal-article"
    assert elife.title.startswith("Styxl2 regulates de novo sarcomere assembly")
    online = elife.dates["published-online"]
    assert (online.value, online.precision) == (datetime(2024, 6, 3, tzinfo=UTC), DatePrecision.DAY)
    assert elife.related_dois("has-preprint") == ["10.1101/2022.10.22.513336"]
    assert classify(elife)[0].value == "published"


def test_biorxiv_preprint_in_crossref() -> None:
    preprint = work("10.1101/2022.10.22.513336")
    assert (preprint.type, preprint.subtype, preprint.institution) == (
        "posted-content",
        "preprint",
        "bioRxiv",
    )
    assert preprint.is_preprint
    assert "<i>" not in preprint.title and "de novo" in preprint.title  # JATS stripped
    assert preprint.dates["posted"].value == datetime(2022, 10, 22, tzinfo=UTC)
    # Crossref's "accepted" on a bioRxiv record is the v3 posting date, not an acceptance.
    assert preprint.dates["accepted"].value == datetime(2023, 11, 26, tzinfo=UTC)
    assert "10.7554/elife.87434" in preprint.related_dois("is-preprint-of")
    kind, server, label = classify(preprint)
    assert (kind.value, server, label.value) == (
        "preprint",
        "biorxiv",
        "preprint_not_peer_reviewed",
    )


def test_month_precision_and_reprint_metadata() -> None:
    ijtp = work("10.1023/a:1026654312961")
    assert ijtp.container_title == "International Journal of Theoretical Physics"
    assert ijtp.dates["issued"].precision is DatePrecision.MONTH
    assert ijtp.dates["issued"].parts == (1999, 4)
    assert "published-online" not in ijtp.dates
    assert ijtp.authors[0].family == "Maldacena"


def test_reply_relation_and_authorless_record() -> None:
    reply = work("10.3390/insects17070713")
    assert reply.related_dois("is-reply-to") == ["10.3390/insects17070712"]
    primer_summary = work("10.1038/s43586-024-00304-8")
    assert primer_summary.title == "Graph neural networks" and primer_summary.authors == ()


def test_parse_date_precisions() -> None:
    assert parse_date({"date-parts": [[2024]]}).precision is DatePrecision.YEAR  # type: ignore[union-attr]
    assert parse_date({"date-parts": [[None]]}) is None
    assert parse_date(None) is None
    assert clean_markup("<jats:p>Abstract</jats:p><jats:p>A &amp; B</jats:p>") == "A & B"


def make(time: FakeTime) -> tuple[CrossrefClient, FixtureTransport, InProcessRateLimiter]:
    transport = FixtureTransport()
    limiter = InProcessRateLimiter(time, time.sleep)

    class Records:
        async def save(self, *args: object, **kwargs: object) -> object:
            import uuid

            return uuid.uuid4()

    client = SourceClient(
        CROSSREF_POLICY,
        httpx.AsyncClient(transport=transport),
        limiter,
        MemoryHttpCache(time),
        clock=time,
        sleep=time.sleep,
    )
    return CrossrefClient(client, Records()), transport, limiter  # type: ignore[arg-type]


async def test_unknown_doi_is_not_found() -> None:
    client, _, _ = make(FakeTime())
    with pytest.raises(SourceNotFound):
        await client.fetch("10.1234/rp-does-not-exist")


async def test_cursor_pagination_follows_next_cursor_and_respects_rate_limit() -> None:
    time = FakeTime()
    client, transport, limiter = make(time)
    results = await client.search(
        filters={
            "relation.type": "has-preprint",
            "from-pub-date": "2024-06-03",
            "until-pub-date": "2024-06-03",
            "type": "journal-article",
        },
        rows=2,
        max_results=4,
    )
    assert len(results) == 4
    cursors = [r.url.params["cursor"] for r in transport.requests]
    assert cursors[0] == "*" and cursors[1] != "*"  # second page uses next-cursor
    assert len({r.work.doi for r in results}) == 4
    assert limiter.waits == [0.0, CROSSREF_POLICY.min_interval_seconds]
    assert SourceName.CROSSREF is client._client.source
