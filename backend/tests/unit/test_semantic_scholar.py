"""Semantic Scholar client: recorded authenticated responses (2026-11-11), authenticated and
unauthenticated modes, global rate limit across endpoints, 429 handling, key secrecy."""

from __future__ import annotations

import io
import json
import uuid
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import UTC, datetime
from itertools import pairwise

import httpx
import pytest

from researchpilot.core.logging import configure_logging
from researchpilot.domain.enums import DatePrecision, SourceName
from researchpilot.domain.identifiers import Identifier, IdentifierScheme, parse_identifier
from researchpilot.integrations.base import (
    InProcessRateLimiter,
    MemoryHttpCache,
    SourceClient,
    SourceError,
    SourceNotFound,
)
from researchpilot.integrations.semantic_scholar import (
    S2_MIN_INTERVAL_SECONDS,
    S2_POLICY,
    SemanticScholarClient,
    parse_paper,
)
from tests.fixtures.source_transport import SOURCES, FixtureTransport
from tests.unit.test_source_client import FakeTime

S2 = SOURCES / "semantic_scholar"
# A random placeholder generated per run (no key-like literal in the repository); it must
# never appear in output.
KEY = f"placeholder-{uuid.uuid4().hex}"


class Records:
    async def save(self, *args: object, **kwargs: object) -> uuid.UUID:
        return uuid.uuid4()


def ids(*texts: str) -> set[Identifier]:
    return {Identifier(p.scheme, p.value) for p in map(parse_identifier, texts)}


def make(
    time: FakeTime, key: str | None
) -> tuple[SemanticScholarClient, FixtureTransport, InProcessRateLimiter, list[datetime]]:
    transport = FixtureTransport()
    seen: list[datetime] = []
    original = transport.handle_async_request

    async def stamped(request: httpx.Request) -> httpx.Response:
        seen.append(time.now())
        return await original(request)

    transport.handle_async_request = stamped  # type: ignore[method-assign]
    limiter = InProcessRateLimiter(time, time.sleep)
    policy = S2_POLICY if key else replace(S2_POLICY, max_attempts=1)
    client = SourceClient(
        policy,
        httpx.AsyncClient(transport=transport),
        limiter,
        MemoryHttpCache(time),
        clock=time,
        sleep=time.sleep,
        headers={"x-api-key": key} if key else None,
    )
    return SemanticScholarClient(client, Records()), transport, limiter, seen  # type: ignore[arg-type]


def test_policy_is_one_shared_budget_at_1_25_seconds() -> None:
    assert S2_MIN_INTERVAL_SECONDS == 1.25
    assert S2_POLICY.min_interval_seconds == 1.25
    assert S2_POLICY.limit_key is SourceName.SEMANTIC_SCHOLAR


def test_parse_recorded_papers() -> None:
    resnet = parse_paper(json.loads((S2 / "paper_ARXIV_1512.03385.json").read_text()))
    assert resnet.paper_id == "2c03df8b48bf3fa39054345bafabfeff15bfd11d"
    assert ids("arXiv:1512.03385", "doi:10.1109/cvpr.2016.90", "CorpusId:206594692") <= set(
        resnet.listed_identifiers
    )
    assert resnet.reported_date() == (datetime(2015, 12, 10, tzinfo=UTC), DatePrecision.DAY)
    # The eLife record lists no bioRxiv DOI; its date is the bioRxiv v3 posting date.
    elife = parse_paper(json.loads((S2 / "paper_DOI_10.7554_elife.87434.json").read_text()))
    assert not any(i.value.startswith("10.1101/") for i in elife.listed_identifiers)
    assert elife.publication_date is not None and elife.publication_date.isoformat() == "2023-11-26"


async def test_authenticated_endpoints_and_pagination() -> None:
    time = FakeTime()
    client, transport, _, _ = make(time, KEY)
    fetched = await client.fetch(Identifier(IdentifierScheme.ARXIV, "1512.03385"))
    assert fetched.paper.title == "Deep Residual Learning for Image Recognition"
    page1 = await client.search("deep residual learning image recognition", limit=2)
    page2 = await client.search(
        "deep residual learning image recognition", limit=2, offset=page1.next_offset or 0
    )
    assert (page1.total, page1.next_offset, page2.next_offset) == (55050, 2, 4)
    assert {h.paper.paper_id for h in page1.hits}.isdisjoint({h.paper.paper_id for h in page2.hits})
    refs = await client.references(fetched.paper.paper_id, limit=3)
    assert (len(refs.papers), refs.next_offset) == (3, 3)
    assert all(r.headers["x-api-key"] == KEY for r in transport.requests)
    with pytest.raises(SourceNotFound):
        await client.fetch(Identifier(IdentifierScheme.DOI, "10.1234/rp-does-not-exist"))


async def test_requests_across_endpoints_never_exceed_the_global_rate() -> None:
    """Lookups, searches and reference pages share one slot sequence: consecutive requests
    are at least 1.25 s apart whichever endpoint they hit."""
    time = FakeTime()
    client, _, _, seen = make(time, KEY)
    await client.fetch(Identifier(IdentifierScheme.ARXIV, "1512.03385"))
    await client.search("deep residual learning image recognition", limit=2)
    await client.references("2c03df8b48bf3fa39054345bafabfeff15bfd11d", limit=3)
    await client.fetch(Identifier(IdentifierScheme.DOI, "10.7554/elife.87434"))
    await client.search("deep residual learning image recognition", limit=2, offset=2)
    gaps = [(b - a).total_seconds() for a, b in pairwise(seen)]
    assert len(seen) == 5 and min(gaps) >= S2_MIN_INTERVAL_SECONDS


async def test_unauthenticated_mode_sends_no_key_and_does_not_retry() -> None:
    client, transport, _, _ = make(FakeTime(), None)
    with pytest.raises(SourceError) as info:
        await client.fetch(Identifier(IdentifierScheme.ARXIV, "1512.03385"))
    assert info.value.upstream_status == 429
    assert transport.count("api.semanticscholar.org") == 1
    assert "x-api-key" not in transport.requests[0].headers


async def test_429_without_retry_after_backs_off_globally_then_succeeds() -> None:
    time = FakeTime()
    client, transport, _limiter, seen = make(time, KEY)
    answers = iter(
        [
            httpx.Response(429, text=(S2 / "burst_429_with_key.json").read_text()),
            httpx.Response(429),
            httpx.Response(200, text=(S2 / "paper_ARXIV_1512.03385.json").read_text()),
        ]
    )
    transport.overrides["api.semanticscholar.org"] = lambda r: next(answers)
    fetched = await client.fetch(Identifier(IdentifierScheme.ARXIV, "1512.03385"))
    assert fetched.paper.paper_id.startswith("2c03df8b")
    gaps = [(b - a).total_seconds() for a, b in pairwise(seen)]
    # jittered exponential backoff (2 s base), always at least the minimum interval
    assert len(seen) == 3 and gaps[0] >= 1.0 and gaps[1] >= 2.0
    assert all(g >= S2_MIN_INTERVAL_SECONDS for g in gaps)


async def test_retry_after_is_honoured_for_the_whole_source() -> None:
    time = FakeTime()
    client, transport, _limiter, seen = make(time, KEY)
    answers = iter(
        [
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, text=(S2 / "paper_ARXIV_1512.03385.json").read_text()),
        ]
    )
    transport.overrides["api.semanticscholar.org"] = lambda r: next(answers)
    await client.fetch(Identifier(IdentifierScheme.ARXIV, "1512.03385"))
    assert (seen[1] - seen[0]).total_seconds() == 7.0


async def test_persistent_429_opens_the_breaker_and_degrades_gracefully() -> None:
    time = FakeTime()
    client, transport, _, _ = make(time, KEY)
    transport.overrides["api.semanticscholar.org"] = lambda r: httpx.Response(429)
    for n in range(3):
        with pytest.raises(SourceError):
            await client.fetch(Identifier(IdentifierScheme.ARXIV, f"1512.0338{n}"))
    assert client._client.degraded
    requests = transport.count("api.semanticscholar.org")
    with pytest.raises(SourceError):  # fails fast while degraded: no request
        await client.fetch(Identifier(IdentifierScheme.ARXIV, "1706.03762"))
    assert transport.count("api.semanticscholar.org") == requests


async def test_the_key_never_appears_in_logs_or_errors() -> None:
    out = io.StringIO()
    with redirect_stdout(out):
        configure_logging("DEBUG", True, [KEY])
        time = FakeTime()
        client, transport, _, _ = make(time, KEY)
        transport.overrides["api.semanticscholar.org"] = lambda r: httpx.Response(429)
        with pytest.raises(SourceError) as info:
            await client.fetch(Identifier(IdentifierScheme.ARXIV, "1512.03385"))
        import structlog

        structlog.get_logger("test").warning("header echo", header=f"x-api-key: {KEY}")
    text = out.getvalue()
    assert "source.retry" in text  # the retries were logged ...
    assert KEY not in text  # ... without the key, even when something tries to log it
    assert KEY not in str(info.value) and KEY not in json.dumps(info.value.extra)
    configure_logging("INFO", True, [])
