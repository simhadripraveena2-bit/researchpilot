"""Live checks against the real arXiv API (opt-in: RP_LIVE_SOURCES=1).

They confirm that the behaviour recorded in tests/fixtures/sources/arxiv and
docs/integrations/ARXIV.md still holds. Not run in CI.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx
import pytest

from researchpilot.domain.identifiers import parse_identifier
from researchpilot.integrations.arxiv import API_URL, ARXIV_POLICY, ArxivClient, parse_feed
from researchpilot.integrations.base import (
    InProcessRateLimiter,
    MemoryHttpCache,
    SourceClient,
    SourceError,
    SourceNotFound,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RP_LIVE_SOURCES") != "1", reason="live source checks are opt-in"
)


class _Records:
    async def save(self, *args: object, **kwargs: object) -> object:
        import uuid

        return uuid.uuid4()


@pytest.fixture
async def arxiv() -> ArxivClient:
    http = httpx.AsyncClient(headers={"User-Agent": "ResearchPilot/0.1 (live-test)"})
    client = SourceClient(ARXIV_POLICY, http, InProcessRateLimiter(), MemoryHttpCache())
    return ArxivClient(client, _Records())  # type: ignore[arg-type]


async def test_published_is_v1_and_updated_is_latest_submission(arxiv: ArxivClient) -> None:
    fetched = await arxiv.fetch(parse_identifier("1706.03762"))
    entry = fetched.entry
    assert entry.latest_version >= 7
    assert entry.submitted_v1 == datetime(2017, 6, 12, 17, 57, 34, tzinfo=UTC)
    assert entry.submitted_latest >= datetime(2023, 8, 2, tzinfo=UTC)


async def test_unknown_id_is_not_found(arxiv: ArxivClient) -> None:
    with pytest.raises(SourceNotFound):
        await arxiv.fetch(parse_identifier("2401.99999"))


async def test_old_style_id_with_version_fails_but_without_version_works(
    arxiv: ArxivClient,
) -> None:
    """Versioned old-style IDs fail: HTTP 500 when the slash is percent-encoded (as httpx
    sends it), or HTTP 200 with an error entry when it is literal. The client therefore
    always queries old-style IDs without a version."""
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.get(API_URL, params={"id_list": "hep-th/9711200v2"})
    if response.status_code == 200:
        with pytest.raises(SourceError):
            parse_feed(response.text)
    else:
        assert response.status_code >= 500
    fetched = await arxiv.fetch(parse_identifier("hep-th/9711200v2"))
    assert fetched.entry.arxiv_id == "hep-th/9711200"
    assert fetched.entry.doi == "10.1023/A:1026654312961"
