"""bioRxiv/medRxiv parsing, pagination and shared rate limit (recorded 2026-11-11)."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from researchpilot.domain.enums import SourceName
from researchpilot.integrations.base import (
    InProcessRateLimiter,
    MemoryHttpCache,
    SourceClient,
    SourceNotFound,
)
from researchpilot.integrations.biorxiv import (
    BIORXIV_POLICY,
    MEDRXIV_POLICY,
    PreprintServerClient,
    is_server_preprint_doi,
    likely_server,
    parse_link,
    parse_page,
    parse_preprint,
)
from tests.fixtures.source_transport import SOURCES, FixtureTransport
from tests.unit.test_source_client import FakeTime

BX = SOURCES / "biorxiv"


def load(name: str) -> str:
    return (BX / name).read_text()


def test_versions_and_published_link() -> None:
    page = parse_page(
        load("details_biorxiv_10.1101_2022.10.22.513336.json"), SourceName.BIORXIV_API
    )
    p = parse_preprint(SourceName.BIORXIV_API, "10.1101/2022.10.22.513336", list(page.rows))
    assert [(v.version, v.posted) for v in p.versions] == [
        (1, date(2022, 10, 22)),
        (2, date(2023, 3, 4)),
        (3, date(2023, 11, 26)),
    ]
    assert p.published_doi == "10.7554/elife.87434"
    assert p.latest.authors[0] == "Chen, X." and "Gao, C." in p.latest.authors  # v3 added an author


def test_no_posts_found_is_an_empty_page() -> None:
    for name in (
        "details_biorxiv_10.1101_2099.01.01.000000.json",
        "details_biorxiv_10.1101_2023.12.14.23299828.json",
    ):  # medRxiv DOI on bioRxiv
        page = parse_page(load(name), SourceName.BIORXIV_API)
        assert (page.rows, page.total, page.next_cursor) == ([], 0, None)


def test_interval_pages_use_item_offsets() -> None:
    first = parse_page(
        load("details_biorxiv_2024-06-03_2024-06-03_0.json"), SourceName.BIORXIV_API, 0
    )
    assert (len(first.rows), first.total, first.next_cursor) == (30, 301, 30)
    later = parse_page(
        load("details_biorxiv_2024-06-03_2024-06-03_100.json"), SourceName.BIORXIV_API, 100
    )
    assert later.next_cursor == 130
    assert {r["doi"] for r in first.rows}.isdisjoint({r["doi"] for r in later.rows})
    pubs = parse_page(load("pubs_biorxiv_2024-06-03_2024-06-03_0.json"), SourceName.BIORXIV_API, 0)
    assert (len(pubs.rows), pubs.next_cursor) == (49, None)
    link = parse_link(pubs.rows[0])
    assert link.preprint_doi.startswith("10.1101/") and link.published_journal


def test_last_page_has_no_next_cursor() -> None:
    body = json.dumps(
        {"messages": [{"status": "ok", "count": 11, "total": "301"}], "collection": [{}] * 11}
    )
    assert parse_page(body, SourceName.BIORXIV_API, 290).next_cursor is None


def test_server_preprint_doi_shapes() -> None:
    assert is_server_preprint_doi("10.1101/2022.10.22.513336")
    assert is_server_preprint_doi("https://doi.org/10.1101/2023.12.14.23299828")
    assert not is_server_preprint_doi("10.1101/gad.1234.110")  # Genes & Development
    assert likely_server("10.1101/2023.12.14.23299828") is SourceName.MEDRXIV_API
    assert likely_server("10.1101/2022.10.22.513336") is SourceName.BIORXIV_API


def make(time: FakeTime, limiter: InProcessRateLimiter, policy=BIORXIV_POLICY):  # type: ignore[no-untyped-def]
    class Records:
        async def save(self, *args: object, **kwargs: object) -> object:
            import uuid

            return uuid.uuid4()

    transport = FixtureTransport()
    client = SourceClient(
        policy,
        httpx.AsyncClient(transport=transport),
        limiter,
        MemoryHttpCache(time),
        clock=time,
        sleep=time.sleep,
    )
    return PreprintServerClient(client, Records()), transport  # type: ignore[arg-type]


async def test_unknown_doi_is_not_found_and_biorxiv_medrxiv_share_one_budget() -> None:
    time = FakeTime()
    limiter = InProcessRateLimiter(time, time.sleep)
    biorxiv, _ = make(time, limiter)
    medrxiv, _ = make(time, limiter, MEDRXIV_POLICY)
    with pytest.raises(SourceNotFound):
        await biorxiv.fetch("10.1101/2099.01.01.000000")
    fetched = await medrxiv.fetch("10.1101/2023.12.14.23299828")
    assert fetched.preprint.server is SourceName.MEDRXIV_API
    assert limiter.waits == [0.0, 1.0]  # one shared slot sequence for the host


async def test_interval_pagination_follows_the_cursor() -> None:
    time = FakeTime()
    client, transport = make(time, InProcessRateLimiter(time, time.sleep))
    total, pages = 75, []

    def server(request: httpx.Request) -> httpx.Response:
        cursor = int(request.url.path.rsplit("/", 1)[-1])
        pages.append(cursor)
        n = min(30, total - cursor)
        return httpx.Response(
            200,
            json={
                "messages": [{"status": "ok", "cursor": cursor, "count": n, "total": str(total)}],
                "collection": [{"doi": f"10.1101/x.{cursor + i}"} for i in range(n)],
            },
        )

    transport.overrides["api.biorxiv.org"] = server
    rows = await client.details_in_interval(date(2024, 6, 3), date(2024, 6, 3))
    assert pages == [0, 30, 60] and len(rows) == 75
