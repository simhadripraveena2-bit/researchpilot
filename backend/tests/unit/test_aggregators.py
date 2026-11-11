"""OpenAlex and Semantic Scholar clients (recorded 2026-11-11; S2 success is constructed)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from researchpilot.core.settings import Settings
from researchpilot.domain.enums import DatePrecision, SourceName
from researchpilot.domain.identifiers import Identifier, IdentifierScheme, parse_identifier
from researchpilot.integrations.base import (
    InProcessRateLimiter,
    MemoryHttpCache,
    SourceBudgetExhausted,
    SourceClient,
    SourceError,
    SourceNotFound,
)
from researchpilot.integrations.openalex import (
    OPENALEX_POLICY,
    OpenAlexBudget,
    OpenAlexClient,
    parse_work,
)
from researchpilot.integrations.semantic_scholar import (
    S2_POLICY,
    SemanticScholarClient,
    parse_paper,
)
from tests.fixtures.source_transport import SOURCES, FixtureTransport
from tests.unit.test_source_client import FakeTime

OA = SOURCES / "openalex"


class Records:
    async def save(self, *args: object, **kwargs: object) -> uuid.UUID:
        return uuid.uuid4()


def oa_work(name: str):  # type: ignore[no-untyped-def]
    return parse_work(json.loads((OA / name).read_text()))


def ids(*texts: str) -> set[Identifier]:
    return {Identifier(p.scheme, p.value) for p in map(parse_identifier, texts)}


def test_openalex_merges_preprint_and_journal_into_one_work() -> None:
    work = oa_work("works_doi_10.1101_2022.10.22.513336.json")
    assert work.id == "W4372330081"
    assert ids("doi:10.7554/elife.87434", "doi:10.1101/2022.10.22.513336") <= set(
        work.listed_identifiers
    )
    # Neither the preprint posting (2022-10-22) nor the journal date (2024-06-03):
    assert work.reported_date() == (datetime(2023, 5, 5, tzinfo=UTC), DatePrecision.DAY)


def test_openalex_filled_in_days_and_months_lose_precision() -> None:
    cvpr = oa_work("works_doi_10.1109_cvpr.2016.90.json")
    assert cvpr.publication_date == "2016-06-01"
    assert cvpr.reported_date() == (datetime(2016, 6, 1, tzinfo=UTC), DatePrecision.MONTH)
    atmp = oa_work("works_doi_10.4310_atmp.1998.v2.n2.a1.json")
    assert atmp.reported_date() == (datetime(1998, 1, 1, tzinfo=UTC), DatePrecision.YEAR)


def test_openalex_arxiv_work_lists_the_arxiv_id() -> None:
    work = oa_work("works_doi_10.48550_arxiv.1512.03385.json")
    assert (work.type, ids("arXiv:1512.03385") <= set(work.listed_identifiers)) == (
        "preprint",
        True,
    )
    assert work.created_date and work.updated_date


def make_openalex(time: FakeTime, capabilities: str = "basic", cap: float = 0.10):  # type: ignore[no-untyped-def]
    transport = FixtureTransport()
    budget = OpenAlexBudget(cap, clock=time)
    client = SourceClient(
        OPENALEX_POLICY,
        httpx.AsyncClient(transport=transport),
        InProcessRateLimiter(time, time.sleep),
        MemoryHttpCache(time),
        clock=time,
        sleep=time.sleep,
        budget=budget,
    )
    return OpenAlexClient(client, Records(), capabilities), transport, budget  # type: ignore[arg-type]


async def test_openalex_unknown_work_is_not_found() -> None:
    client, _, _ = make_openalex(FakeTime())
    with pytest.raises(SourceNotFound):
        await client.fetch(Identifier(IdentifierScheme.OPENALEX, "W999999999999"))


async def test_budget_429_stops_metered_requests_without_retrying() -> None:
    """Recorded: a filter query with the keyless budget used up -> 429, credits required,
    Retry-After to midnight. One request, no retries; later list requests are refused
    locally; single-work lookups (cost $0) still work."""
    time = FakeTime()
    client, transport, budget = make_openalex(time)
    recorded = json.loads((OA / "_recorded.json").read_text())[
        "works_filter_doi_budget_exhausted.json"
    ]
    transport.overrides["api.openalex.org"] = lambda r: (
        httpx.Response(
            429,
            text=(OA / "works_filter_doi_budget_exhausted.json").read_text(),
            headers=recorded["headers"],
        )
        if r.url.path == "/works"
        else httpx.Response(
            200,
            text=(OA / "works_doi_10.1109_cvpr.2016.90.json").read_text(),
            headers={"x-ratelimit-cost-usd": "0", "x-ratelimit-remaining-usd": "0"},
        )
    )
    with pytest.raises(SourceBudgetExhausted):
        await client.search_page(search="residual learning")
    assert transport.count("api.openalex.org") == 1
    assert budget.blocked_until is not None and budget.blocked_until > time.now() + timedelta(
        hours=10
    )
    with pytest.raises(SourceBudgetExhausted):  # refused locally, no request
        await client.search_page(search="residual learning")
    assert transport.count("api.openalex.org") == 1
    fetched = await client.fetch(Identifier(IdentifierScheme.DOI, "10.1109/cvpr.2016.90"))
    assert fetched.work.id == "W2194775991"


def test_own_daily_cap_and_daily_reset() -> None:
    time = FakeTime()
    budget = OpenAlexBudget(0.0002, clock=time)
    response = httpx.Response(200, headers={"x-ratelimit-cost-usd": "0.0001"})
    budget.observe("search", response)
    budget.check("search")
    budget.observe("search", response)
    with pytest.raises(SourceBudgetExhausted):
        budget.check("search")
    budget.check("entity")  # free lookups stay allowed
    time.at += timedelta(days=1)
    budget.check("search")  # a new day


def test_capability_switch_both_paths() -> None:
    basic, _, _ = make_openalex(FakeTime())
    premium, _, _ = make_openalex(FakeTime(), "premium")
    since = date(2026, 11, 4)
    assert basic.search_params(search="gnn", published_from=since)["filter"] == (
        "from_publication_date:2026-11-04"
    )
    with pytest.raises(SourceError, match="premium"):
        basic.search_params(search="gnn", indexed_from=since)  # never silently replaced
    assert premium.search_params(search="gnn", indexed_from=since)["filter"] == (
        "from_created_date:2026-11-04"
    )


# --- Semantic Scholar -------------------------------------------------------------------

S2 = SOURCES / "semantic_scholar"


def test_s2_parse_constructed_record() -> None:
    meta = json.loads((S2 / "_recorded.json").read_text())[
        "paper_arxiv_1512.03385_CONSTRUCTED.json"
    ]
    assert meta["constructed"] is True  # not a recording; see the note in _recorded.json
    paper = parse_paper(json.loads((S2 / "paper_arxiv_1512.03385_CONSTRUCTED.json").read_text()))
    assert ids("arXiv:1512.03385", "doi:10.1109/cvpr.2016.90", "CorpusId:206594692") <= set(
        paper.listed_identifiers
    )
    assert paper.reported_date() == (datetime(2015, 12, 10, tzinfo=UTC), DatePrecision.DAY)


def make_s2(time: FakeTime, key: str | None):  # type: ignore[no-untyped-def]
    from dataclasses import replace

    transport = FixtureTransport()
    policy = S2_POLICY if key else replace(S2_POLICY, max_attempts=1)
    client = SourceClient(
        policy,
        httpx.AsyncClient(transport=transport),
        InProcessRateLimiter(time, time.sleep),
        MemoryHttpCache(time),
        clock=time,
        sleep=time.sleep,
        headers={"x-api-key": key} if key else None,
    )
    return SemanticScholarClient(client, Records()), transport  # type: ignore[arg-type]


async def test_s2_without_key_one_attempt_then_unavailable() -> None:
    client, transport = make_s2(FakeTime(), None)
    with pytest.raises(SourceError) as info:
        await client.fetch(Identifier(IdentifierScheme.ARXIV, "1706.03762"))
    assert info.value.upstream_status == 429
    assert transport.count("api.semanticscholar.org") == 1


async def test_s2_with_key_sends_header_and_retries_429() -> None:
    time = FakeTime()
    client, transport = make_s2(time, "dummy-key")
    answers = iter(
        [
            httpx.Response(429),
            httpx.Response(200, text=(S2 / "paper_arxiv_1512.03385_CONSTRUCTED.json").read_text()),
        ]
    )
    transport.overrides["api.semanticscholar.org"] = lambda r: next(answers)
    fetched = await client.fetch(Identifier(IdentifierScheme.ARXIV, "1512.03385"))
    assert fetched.paper.paper_id == "2c03df8b48bf3fa39054345bafabfeff15bfd11d"
    assert all(r.headers.get("x-api-key") == "dummy-key" for r in transport.requests)
    assert len(transport.requests) == 2 and time.sleeps  # backed off, then succeeded


def test_registry_uses_keys_only_when_configured() -> None:
    from researchpilot.integrations.registry import _bearer, _key

    assert _key(None) == {} and _bearer(None) == {}
    assert _key(SecretStr("k")) == {"x-api-key": "k"}
    assert _bearer(SecretStr("k")) == {"Authorization": "Bearer k"}
    assert Settings(_env_file=None).openalex_capabilities == "basic"
    assert SourceName.OPENALEX
