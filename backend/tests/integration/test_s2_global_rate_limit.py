"""Semantic Scholar: one global, cross-process rate limit for all endpoints (Postgres).

Two independent source registries - as built by the API process and by the worker - each
with its own database engine, use the production ``PostgresRateLimiter`` with real waiting.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from itertools import pairwise

import httpx
import pytest
from pydantic import SecretStr

from researchpilot.core.settings import Settings
from researchpilot.db.session import make_engine, make_sessionmaker
from researchpilot.domain.identifiers import Identifier, IdentifierScheme
from researchpilot.integrations.base import SourceError
from researchpilot.integrations.registry import Sources, build_sources
from researchpilot.integrations.semantic_scholar import S2_MIN_INTERVAL_SECONDS
from tests.fixtures.source_transport import FixtureTransport
from tests.integration.conftest import TEST_S2_KEY

pytestmark = pytest.mark.integration

TOLERANCE = 0.05  # clock/scheduling noise between processes


class Timed(FixtureTransport):
    """Records the real (monotonic) time each Semantic Scholar request leaves."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[float] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.semanticscholar.org":
            self.sent.append(time.monotonic())
        return await super().handle_async_request(request)


async def two_processes(
    settings: Settings, transport: FixtureTransport
) -> AsyncIterator[tuple[Sources, Sources]]:
    keyed = settings.model_copy(update={"s2_api_key": SecretStr(TEST_S2_KEY)})
    engines = [make_engine(settings.database_url) for _ in range(2)]
    registries = [build_sources(keyed, make_sessionmaker(e), transport) for e in engines]
    try:
        yield registries[0], registries[1]
    finally:
        for r in registries:
            await r.aclose()
        for e in engines:
            await e.dispose()


def gaps(times: list[float]) -> list[float]:
    ordered = sorted(times)
    return [b - a for a, b in pairwise(ordered)]


async def test_api_and_worker_share_one_rate_limit_across_all_endpoints(
    settings: Settings,
) -> None:
    transport = Timed()
    async for api, worker in two_processes(settings, transport):
        s2_api, s2_worker = api.semantic_scholar, worker.semantic_scholar
        await asyncio.gather(  # all at once, from both processes, four endpoints/calls
            s2_api.fetch(Identifier(IdentifierScheme.ARXIV, "1512.03385")),
            s2_worker.search("deep residual learning image recognition", limit=2),
            s2_api.references("2c03df8b48bf3fa39054345bafabfeff15bfd11d", limit=3),
            s2_worker.fetch(Identifier(IdentifierScheme.DOI, "10.1109/cvpr.2016.90")),
        )
    assert len(transport.sent) == 4
    assert min(gaps(transport.sent)) >= S2_MIN_INTERVAL_SECONDS - TOLERANCE
    assert all("x-api-key" in r.headers for r in transport.requests)


async def test_a_429_in_one_process_holds_back_the_other(settings: Settings) -> None:
    transport = Timed()
    first = {"done": False}

    def limited_once(request: httpx.Request) -> httpx.Response:
        if not first["done"]:
            first["done"] = True
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, text='{"paperId": "2c03df8b48bf3fa39054345bafabfeff15bfd11d"}')

    transport.overrides["api.semanticscholar.org"] = limited_once
    async for api, worker in two_processes(settings, transport):
        api_task = asyncio.create_task(
            api.semantic_scholar.fetch(Identifier(IdentifierScheme.ARXIV, "1512.03385"))
        )
        await asyncio.sleep(0.2)  # the API's request got the 429 and deferred the slot
        await worker.semantic_scholar.fetch(Identifier(IdentifierScheme.ARXIV, "1706.03762"))
        await api_task
    # Retry-After: 3 applied to the whole source: the worker's request waited for it too.
    assert len(transport.sent) == 3
    assert transport.sent[1] - transport.sent[0] >= 3.0 - TOLERANCE
    assert min(gaps(transport.sent)) >= S2_MIN_INTERVAL_SECONDS - TOLERANCE


async def test_unauthenticated_processes_do_not_send_a_key(settings: Settings) -> None:
    transport = FixtureTransport()
    engine = make_engine(settings.database_url)
    sources = build_sources(settings, make_sessionmaker(engine), transport, rate_limits=False)
    try:
        with pytest.raises(SourceError):
            await sources.semantic_scholar.fetch(Identifier(IdentifierScheme.ARXIV, "1512.03385"))
    finally:
        await sources.aclose()
        await engine.dispose()
    assert [("x-api-key" in r.headers) for r in transport.requests] == [False]
