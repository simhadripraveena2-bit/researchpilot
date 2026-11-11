"""Serves recorded source responses (tests/fixtures/sources) instead of the network.

arXiv responses are looked up by ``id_list``; other sources by the exact recorded request
(``<source>/_recorded.json``: URL, status and headers per file), with query parameters
compared regardless of order.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

import httpx

SOURCES = Path(__file__).parent / "sources"

EMPTY_ARXIV_FEED = (SOURCES / "arxiv" / "api_not_found_2401.99999.xml").read_text()

HOST_DIRS = {
    "api.crossref.org": "crossref",
    "api.biorxiv.org": "biorxiv",
    "api.semanticscholar.org": "semantic_scholar",
    "api.openalex.org": "openalex",
    "rss.arxiv.org": "arxiv_rss",
}


def _key(url: str) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    parts = urlsplit(url)
    return (
        parts.netloc.lower(),
        unquote(parts.path).lower(),
        tuple(sorted(parse_qsl(parts.query, keep_blank_values=True))),
    )


def _index() -> dict[tuple[str, str, tuple[tuple[str, str], ...]], tuple[Path, dict[str, object]]]:
    index = {}
    for directory in HOST_DIRS.values():
        log = SOURCES / directory / "_recorded.json"
        if not log.exists():
            continue
        for name, meta in json.loads(log.read_text()).items():
            index[_key(str(meta["url"]))] = (SOURCES / directory / name, meta)
    return index


class FixtureTransport(httpx.AsyncBaseTransport):
    """Maps a request to a recorded file; unknown requests are a test failure (no network)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.overrides: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self._recorded = _index()

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
        found = self._recorded.get(_key(str(request.url)))
        if found is not None:
            path, meta = found
            headers = {str(k): str(v) for k, v in dict(meta.get("headers") or {}).items()}
            return httpx.Response(int(str(meta["status"])), text=path.read_text(), headers=headers)
        raise AssertionError(f"unexpected outbound request in tests: {request.url}")

    def count(self, host: str) -> int:
        return sum(1 for r in self.requests if r.url.host == host)
