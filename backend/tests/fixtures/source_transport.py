"""Serves recorded source responses (tests/fixtures/sources) instead of the network.

Built on the evaluation harness's ``ReplayTransport`` (same lookup rules), with test
behaviour on top: per-host overrides, an empty arXiv feed for unknown IDs (arXiv's real
answer), and Semantic Scholar's verified 429s without a key or for unrecorded requests.
Any other unrecorded request fails the test (no network).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx

from researchpilot.evaluation.replay import (
    ReplayTransport,
    UnrecordedRequest,
    arxiv_lookup_name,
    request_key,
)

SOURCES = Path(__file__).parent / "sources"

EMPTY_ARXIV_FEED = (SOURCES / "arxiv" / "api_not_found_2401.99999.xml").read_text()

# Semantic Scholar, as verified: without an API key every request got HTTP 429; with a key,
# recorded responses are served and anything unrecorded gets the keyed 429 (rate limited).
S2_UNAUTHENTICATED = SOURCES / "semantic_scholar" / "paper_arxiv_1512.03385_unauthenticated.json"
S2_RATE_LIMITED = SOURCES / "semantic_scholar" / "burst_429_with_key.json"


class FixtureTransport(ReplayTransport):
    """Maps a request to a recorded file; unknown requests are a test failure (no network)."""

    def __init__(self) -> None:
        super().__init__([SOURCES])
        self.overrides: dict[str, Callable[[httpx.Request], httpx.Response]] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host in self.overrides:
            self.requests.append(request)
            return self.overrides[host](request)
        name = arxiv_lookup_name(request)
        if name is not None and self._arxiv_file(name) is None:
            self.requests.append(request)
            return httpx.Response(
                200, text=EMPTY_ARXIV_FEED, headers={"content-type": "application/atom+xml"}
            )
        if host == "api.semanticscholar.org":
            if "x-api-key" not in request.headers:
                self.requests.append(request)
                return httpx.Response(
                    429,
                    text=S2_UNAUTHENTICATED.read_text(),
                    headers={"x-amzn-errortype": "TooManyRequestsException"},
                )
            if request_key(str(request.url)) not in self._index:
                self.requests.append(request)
                return httpx.Response(
                    429,
                    text=S2_RATE_LIMITED.read_text(),
                    headers={"x-amzn-errortype": "TooManyRequestsException"},
                )
        try:
            return await super().handle_async_request(request)
        except UnrecordedRequest as exc:
            raise AssertionError(f"unexpected outbound request in tests: {exc}") from exc
