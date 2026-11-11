"""Serves recorded source responses (tests/fixtures/sources) instead of the network."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx

SOURCES = Path(__file__).parent / "sources"

EMPTY_ARXIV_FEED = (SOURCES / "arxiv" / "api_not_found_2401.99999.xml").read_text()


class FixtureTransport(httpx.AsyncBaseTransport):
    """Maps a request to a recorded file; unknown requests are a test failure (no network)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.overrides: dict[str, Callable[[httpx.Request], httpx.Response]] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host in self.overrides:
            return self.overrides[host](request)
        if host == "export.arxiv.org" and request.url.path == "/api/query":
            ids = request.url.params.get("id_list", "")
            name = "api_" + ids.replace("/", "_").replace(",", "+") + ".xml"
            path = SOURCES / "arxiv" / name
            body = path.read_text() if path.exists() else EMPTY_ARXIV_FEED
            return httpx.Response(200, text=body, headers={"content-type": "application/atom+xml"})
        raise AssertionError(f"unexpected outbound request in tests: {request.url}")

    def count(self, host: str) -> int:
        return sum(1 for r in self.requests if r.url.host == host)
