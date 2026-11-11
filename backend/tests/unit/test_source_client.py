"""SourceClient behaviour: rate limits, retries, Retry-After, circuit breaker, cache (R1-4)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from researchpilot.domain.enums import SourceName
from researchpilot.integrations.base import (
    InProcessRateLimiter,
    MemoryHttpCache,
    SourceClient,
    SourceDegraded,
    SourceError,
    SourceNotFound,
    SourcePolicy,
    cache_key,
    parse_retry_after,
)

T0 = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


class FakeTime:
    """A clock whose sleep advances it: waits are recorded, nothing actually sleeps."""

    def __init__(self) -> None:
        self.at = T0
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.at

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.at += timedelta(seconds=seconds)


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    time: FakeTime,
    **policy: object,
) -> tuple[SourceClient, InProcessRateLimiter, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    limiter = InProcessRateLimiter(time, time.sleep)
    client = SourceClient(
        SourcePolicy(source=SourceName.ARXIV_API, min_interval_seconds=3.0, **policy),  # type: ignore[arg-type]
        httpx.AsyncClient(transport=httpx.MockTransport(record)),
        limiter,
        MemoryHttpCache(time),
        clock=time,
        sleep=time.sleep,
    )
    return client, limiter, seen


async def test_requests_are_spaced_by_the_source_interval() -> None:
    time = FakeTime()
    client, limiter, seen = make_client(lambda r: httpx.Response(200, text="ok"), time)
    for n in range(3):
        await client.get(f"https://export.arxiv.org/api/query?n={n}", use_cache=False)
    assert len(seen) == 3
    assert limiter.waits == [0.0, 3.0, 3.0]  # arXiv: at most one request per 3 s


async def test_retry_after_seconds_is_honoured() -> None:
    time = FakeTime()
    responses = iter([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)])
    client, _, seen = make_client(lambda r: next(responses), time)
    result = await client.get("https://api.semanticscholar.org/x")
    assert result.status == 200
    assert len(seen) == 2
    assert 7.0 in time.sleeps


async def test_retry_after_http_date_is_honoured() -> None:
    time = FakeTime()
    later = format_datetime(T0 + timedelta(seconds=20), usegmt=True)
    responses = iter([httpx.Response(503, headers={"Retry-After": later}), httpx.Response(200)])
    client, _, _ = make_client(lambda r: next(responses), time)
    await client.get("https://api.openalex.org/x")
    assert 20.0 in time.sleeps


async def test_retry_after_beyond_cap_gives_up_instead_of_blocking() -> None:
    time = FakeTime()
    client, _, seen = make_client(
        lambda r: httpx.Response(429, headers={"Retry-After": "3600"}), time
    )
    with pytest.raises(SourceError) as info:
        await client.get("https://api.semanticscholar.org/x")
    assert len(seen) == 1
    assert info.value.upstream_status == 429


async def test_server_errors_retry_with_backoff_then_fail() -> None:
    time = FakeTime()
    client, _, seen = make_client(lambda r: httpx.Response(503), time, max_attempts=3)
    with pytest.raises(SourceError):
        await client.get("https://api.crossref.org/works/x")
    assert len(seen) == 3


async def test_connection_errors_are_retried() -> None:
    time = FakeTime()
    attempts = iter([httpx.ConnectError("down"), httpx.Response(200, text="ok")])

    def handler(request: httpx.Request) -> httpx.Response:
        outcome = next(attempts)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    client, _, _ = make_client(handler, time)
    assert (await client.get("https://api.biorxiv.org/x")).text == "ok"


async def test_client_errors_are_not_retried() -> None:
    time = FakeTime()
    client, _, seen = make_client(lambda r: httpx.Response(400), time)
    with pytest.raises(SourceError):
        await client.get("https://api.crossref.org/works/x")
    assert len(seen) == 1


async def test_not_found_is_not_a_failure() -> None:
    time = FakeTime()
    client, _, _ = make_client(lambda r: httpx.Response(404), time, breaker_threshold=1)
    with pytest.raises(SourceNotFound):
        await client.get("https://api.crossref.org/works/missing")
    assert not client.degraded


async def test_repeated_failures_open_the_circuit_breaker() -> None:
    time = FakeTime()
    client, _, seen = make_client(
        lambda r: httpx.Response(500),
        time,
        max_attempts=1,
        breaker_threshold=2,
        breaker_cooldown=timedelta(minutes=5),
    )
    for _ in range(2):
        with pytest.raises(SourceError):
            await client.get("https://api.openalex.org/x", use_cache=False)
    assert client.degraded
    with pytest.raises(SourceDegraded):  # fails fast, makes no request
        await client.get("https://api.openalex.org/y", use_cache=False)
    assert len(seen) == 2
    time.at += timedelta(minutes=6)
    assert not client.degraded


async def test_cache_hit_makes_no_request_and_is_marked() -> None:
    time = FakeTime()
    client, _, seen = make_client(
        lambda r: httpx.Response(200, text="body"), time, cache_ttl={"entity": timedelta(hours=1)}
    )
    first = await client.get(
        "https://export.arxiv.org/api/query", params={"id_list": "1"}, endpoint_class="entity"
    )
    second = await client.get(
        "https://export.arxiv.org/api/query", params={"id_list": "1"}, endpoint_class="entity"
    )
    assert (first.cache_hit, second.cache_hit) == (False, True)
    assert second.text == "body"
    assert len(seen) == 1
    time.at += timedelta(hours=2)  # expired
    await client.get(
        "https://export.arxiv.org/api/query", params={"id_list": "1"}, endpoint_class="entity"
    )
    assert len(seen) == 2


def test_parse_retry_after() -> None:
    time = FakeTime()
    assert parse_retry_after("12", time) == 12.0
    assert parse_retry_after(None, time) is None
    assert parse_retry_after("soon", time) is None
    past = format_datetime(T0 - timedelta(seconds=30), usegmt=True)
    assert parse_retry_after(past, time) == 0.0


async def test_endpoint_classes_do_not_share_cache_entries() -> None:
    """Same URL and parameters under two endpoint classes with different TTLs: each class
    has its own entry, so a short-lived search entry never serves (or expires) an entity
    lookup, and vice versa. Within one class the cache behaves as before."""
    time = FakeTime()
    bodies = iter(["as search", "as entity", "search again"])
    client, _, seen = make_client(
        lambda r: httpx.Response(200, text=next(bodies)),
        time,
        cache_ttl={"search": timedelta(hours=1), "entity": timedelta(hours=12)},
    )
    url, params = "https://export.arxiv.org/api/query", {"id_list": "1706.03762"}

    search = await client.get(url, params=params, endpoint_class="search")
    entity = await client.get(url, params=params, endpoint_class="entity")
    assert (search.cache_hit, entity.cache_hit) == (False, False)  # no cross-class hit
    assert (search.text, entity.text) == ("as search", "as entity")
    assert len(seen) == 2

    time.at += timedelta(hours=2)  # the search entry has expired, the entity entry has not
    entity_again = await client.get(url, params=params, endpoint_class="entity")
    assert (entity_again.cache_hit, entity_again.text) == (True, "as entity")
    search_again = await client.get(url, params=params, endpoint_class="search")
    assert (search_again.cache_hit, search_again.text) == (False, "search again")
    assert len(seen) == 3


def test_cache_key_depends_on_endpoint_class() -> None:
    url, params = "https://api.crossref.org/works", {"query": "graph"}
    assert cache_key(SourceName.CROSSREF, "search", url, params) != cache_key(
        SourceName.CROSSREF, "entity", url, params
    )
    assert cache_key(SourceName.CROSSREF, "search", url, params) == cache_key(
        SourceName.CROSSREF, "search", url, dict(reversed(list(params.items())))
    )
