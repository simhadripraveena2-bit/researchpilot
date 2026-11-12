"""Replays recorded source responses instead of the network (benchmarks and tests).

Recordings use one layout everywhere: ``<root>/<source dir>/<file>`` plus
``<root>/<source dir>/_recorded.json`` (URL, status, headers per file). arXiv ID lookups are
found by file name (``api_<ids>.xml``); everything else by the exact recorded URL, with query
parameters compared regardless of order. Several roots can be combined (a benchmark split's
own recordings plus shared ones).

In record mode, requests to the listed live hosts that are not recorded yet are sent to the
real API once and saved; nothing is ever overwritten.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlsplit

import httpx

HOST_DIRS = {
    "api.crossref.org": "crossref",
    "api.biorxiv.org": "biorxiv",
    "api.semanticscholar.org": "semantic_scholar",
    "api.openalex.org": "openalex",
    "rss.arxiv.org": "arxiv_rss",
    "export.arxiv.org": "arxiv",  # searches; ID lookups use file names
}
_KEEP_HEADERS = ("content-type", "retry-after")

Key = tuple[str, str, tuple[tuple[str, str], ...]]


class UnrecordedRequest(Exception):
    """A request with no recording (replay never falls back to the network)."""


def request_key(url: str) -> Key:
    parts = urlsplit(url)
    return (
        parts.netloc.lower(),
        unquote(parts.path).lower(),
        tuple(sorted(parse_qsl(parts.query, keep_blank_values=True))),
    )


def arxiv_lookup_name(request: httpx.Request) -> str | None:
    if request.url.host != "export.arxiv.org" or "search_query" in request.url.params:
        return None
    ids = str(request.url.params.get("id_list", ""))
    return "api_" + ids.replace("/", "_").replace(",", "+") + ".xml"


class ReplayTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        roots: Iterable[Path],
        *,
        unrecorded: Callable[[httpx.Request], httpx.Response] | None = None,
        record_to: Path | None = None,
        live_hosts: Iterable[str] = (),
    ) -> None:
        self.roots = [Path(r) for r in roots]
        self.requests: list[httpx.Request] = []
        self.recorded_now: list[str] = []
        self._unrecorded = unrecorded
        self._record_to = record_to
        self._live_hosts = frozenset(live_hosts)
        self._live: httpx.AsyncClient | None = None
        self._index = self._build_index()

    def _build_index(self) -> dict[Key, tuple[Path, dict[str, object]]]:
        index: dict[Key, tuple[Path, dict[str, object]]] = {}
        for root in reversed(self.roots):  # earlier roots win
            for directory in HOST_DIRS.values():
                log = root / directory / "_recorded.json"
                if not log.exists():
                    continue
                for name, meta in json.loads(log.read_text()).items():
                    if meta.get("constructed"):
                        continue  # constructed fixtures are never served as recordings
                    index[request_key(str(meta["url"]))] = (root / directory / name, meta)
        return index

    def _arxiv_file(self, name: str) -> Path | None:
        for root in self.roots:
            path = root / "arxiv" / name
            if path.exists():
                return path
        return None

    def count(self, host: str) -> int:
        return sum(1 for r in self.requests if r.url.host == host)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        name = arxiv_lookup_name(request)
        if name is not None:
            path = self._arxiv_file(name)
            if path is not None:
                return httpx.Response(
                    200, text=path.read_text(), headers={"content-type": "application/atom+xml"}
                )
        else:
            found = self._index.get(request_key(str(request.url)))
            if found is not None:
                path, meta = found
                raw = meta.get("headers") or {}
                assert isinstance(raw, dict)
                headers = {str(k): str(v) for k, v in raw.items()}
                return httpx.Response(
                    int(str(meta["status"])), text=path.read_text(), headers=headers
                )
        if self._record_to is not None and request.url.host in self._live_hosts:
            return await self._record(request, name)
        if self._unrecorded is not None:
            return self._unrecorded(request)
        raise UnrecordedRequest(str(request.url))

    async def _record(self, request: httpx.Request, arxiv_name: str | None) -> httpx.Response:
        assert self._record_to is not None
        if self._live is None:
            self._live = httpx.AsyncClient(trust_env=True, timeout=60)
        live = await self._live.send(
            httpx.Request(request.method, request.url, headers=request.headers)
        )
        body = live.text
        folder = self._record_to / HOST_DIRS[request.url.host]
        folder.mkdir(parents=True, exist_ok=True)
        headers = {
            k: v
            for k, v in live.headers.items()
            if k.lower() in _KEEP_HEADERS or k.lower().startswith("x-ratelimit")
        }
        if arxiv_name is not None:
            (folder / arxiv_name).write_text(body)
            self.recorded_now.append(f"arxiv/{arxiv_name}")
        else:
            url = str(request.url)
            if request.url.host == "api.crossref.org" and request.url.path.startswith("/works/"):
                name = "works_" + quote(request.url.path.removeprefix("/works/"), safe="") + ".json"
            else:
                name = (
                    "rec_"
                    + hashlib.sha256(url.encode()).hexdigest()[:12]
                    + (".xml" if request.url.host.endswith("arxiv.org") else ".json")
                )
            log_path = folder / "_recorded.json"
            log = json.loads(log_path.read_text()) if log_path.exists() else {}
            if name not in log:
                (folder / name).write_text(body)
                log[name] = {
                    "url": url,
                    "status": live.status_code,
                    "headers": headers,
                    "recorded": date.today().isoformat(),
                }
                log_path.write_text(json.dumps(log, indent=1, sort_keys=True))
                self._index[request_key(url)] = (folder / name, log[name])
                self.recorded_now.append(f"{folder.name}/{name}")
        return httpx.Response(live.status_code, text=body, headers=headers)

    async def aclose(self) -> None:
        if self._live is not None:  # recreated on demand: clients sharing this transport
            await self._live.aclose()  # may close it more than once
            self._live = None
