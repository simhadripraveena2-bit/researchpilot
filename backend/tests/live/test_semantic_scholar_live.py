"""Live Semantic Scholar checks (opt-in: RP_LIVE_SOURCES=1 and S2_API_KEY).

In a Claude Code cloud session set S2_API_KEY=proxy-injected: the proxy replaces it with the
configured network secret. Not run in CI.
"""

from __future__ import annotations

import os

import httpx
import pytest

from researchpilot.domain.identifiers import Identifier, IdentifierScheme
from researchpilot.integrations.base import InProcessRateLimiter, MemoryHttpCache, SourceClient
from researchpilot.integrations.semantic_scholar import S2_POLICY, SemanticScholarClient

pytestmark = pytest.mark.skipif(
    os.environ.get("RP_LIVE_SOURCES") != "1" or not os.environ.get("S2_API_KEY"),
    reason="live Semantic Scholar checks need RP_LIVE_SOURCES=1 and S2_API_KEY",
)


class _Records:
    async def save(self, *args: object, **kwargs: object) -> object:
        import uuid

        return uuid.uuid4()


async def test_three_endpoints_with_the_key_through_the_production_policy() -> None:
    http = httpx.AsyncClient(headers={"User-Agent": "ResearchPilot/0.1 (live-test)"})
    client = SourceClient(
        S2_POLICY,
        http,
        InProcessRateLimiter(),
        MemoryHttpCache(),
        headers={"x-api-key": os.environ["S2_API_KEY"]},
    )
    s2 = SemanticScholarClient(client, _Records())  # type: ignore[arg-type]
    paper = (await s2.fetch(Identifier(IdentifierScheme.ARXIV, "1512.03385"))).paper
    assert paper.paper_id == "2c03df8b48bf3fa39054345bafabfeff15bfd11d"
    page = await s2.search("deep residual learning image recognition", limit=2)
    assert page.hits and page.next_offset == 2
    refs = await s2.references(paper.paper_id, limit=3)
    assert len(refs.papers) == 3
    await http.aclose()
