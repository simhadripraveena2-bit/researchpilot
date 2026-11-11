"""bioRxiv and medRxiv API client (api.biorxiv.org; decision D22).

Verified behaviour (2026-11-11; see docs/integrations/BIORXIV.md):

* ``/details/{server}/{doi}`` returns one collection row **per version** (``version``,
  ``date`` = that version's posting date, day precision, title, authors, category, license,
  ``published`` = journal DOI or ``NA``). It is the system of record for posting dates.
* Unknown DOI, or a DOI asked on the other server: HTTP 200 with
  ``messages[0].status = "no posts found"`` and an empty collection (no 404).
* ``/details/{server}/{from}/{to}/{cursor}``: 30 rows per page; the cursor is an item offset
  (``cursor=100`` returns rows 100-129); ``messages[0].total`` is the total.
* ``/pubs/{server}/{from}/{to}/{cursor}``: preprint DOI -> published DOI links
  (``preprint_doi``, ``published_doi``, ``published_journal``, ``preprint_date``,
  ``published_date``), decisive Version Matcher evidence (D29).
* The posting date can differ from the date embedded in the DOI (DOI ``2023.10.03`` posted
  ``2023-10-05``): never derive dates from DOIs.
* bioRxiv and medRxiv share the host; both clients share one request budget.
* ``10.1101/`` is also the prefix of Cold Spring Harbor journals (e.g. ``10.1101/gad.…``);
  only DOIs shaped ``10.1101/YYYY.MM.DD.NNNNNN[NN]`` are preprints.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from researchpilot.domain.enums import SourceName
from researchpilot.domain.identifiers import normalize_doi
from researchpilot.integrations.base import (
    SourceClient,
    SourceError,
    SourceNotFound,
    SourcePolicy,
    SourceRecordStore,
)

API_URL = "https://api.biorxiv.org"
NO_POSTS = "no posts found"
PREPRINT_DOI = re.compile(r"^10\.1101/(\d{4})\.(\d{2})\.(\d{2})\.(\d{6,8})$")


def _policy(source: SourceName) -> SourcePolicy:
    return SourcePolicy(
        source=source,
        min_interval_seconds=1.0,  # no published limit; one request per second, shared
        rate_limit_key=SourceName.BIORXIV_API,
        cache_ttl={"entity": timedelta(hours=12), "search": timedelta(hours=1)},
    )


BIORXIV_POLICY = _policy(SourceName.BIORXIV_API)
MEDRXIV_POLICY = _policy(SourceName.MEDRXIV_API)
SERVER_NAME = {SourceName.BIORXIV_API: "biorxiv", SourceName.MEDRXIV_API: "medrxiv"}


def is_server_preprint_doi(doi: str) -> bool:
    return PREPRINT_DOI.match(normalize_doi(doi)) is not None


def likely_server(doi: str) -> SourceName:
    """medRxiv DOIs carry an 8-digit suffix, bioRxiv DOIs 6 digits (a hint, not a rule:
    lookups fall back to the other server)."""
    match = PREPRINT_DOI.match(normalize_doi(doi))
    if match and len(match.group(4)) == 8:
        return SourceName.MEDRXIV_API
    return SourceName.BIORXIV_API


@dataclass(frozen=True)
class PreprintVersion:
    version: int
    posted: date
    title: str
    authors: tuple[str, ...]
    category: str | None
    license: str | None
    abstract: str | None
    type: str | None
    published_doi: str | None
    jats_url: str | None


@dataclass(frozen=True)
class ServerPreprint:
    server: SourceName
    doi: str
    versions: tuple[PreprintVersion, ...]  # ascending
    raw: list[Mapping[str, Any]]

    @property
    def latest(self) -> PreprintVersion:
        return self.versions[-1]

    @property
    def published_doi(self) -> str | None:
        return next((v.published_doi for v in reversed(self.versions) if v.published_doi), None)


@dataclass(frozen=True)
class FetchedPreprint:
    preprint: ServerPreprint
    source_record_id: uuid.UUID
    fetched_at: datetime
    cache_hit: bool


@dataclass(frozen=True)
class PublicationLink:
    preprint_doi: str
    published_doi: str
    published_journal: str | None
    preprint_date: date | None
    published_date: date | None
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class Page:
    rows: list[Mapping[str, Any]]
    total: int
    next_cursor: int | None


class PreprintServerClient:
    """One client per server (bioRxiv or medRxiv)."""

    def __init__(self, client: SourceClient, records: SourceRecordStore) -> None:
        if client.source not in SERVER_NAME:
            raise ValueError("PreprintServerClient needs a bioRxiv or medRxiv SourceClient")
        self._client = client
        self._records = records
        self.source = client.source
        self.server = SERVER_NAME[client.source]

    async def fetch(self, doi: str) -> FetchedPreprint:
        """All versions of one preprint; ``SourceNotFound`` if this server has no such DOI."""
        normalized = normalize_doi(doi)
        response = await self._client.get(
            f"{API_URL}/details/{self.server}/{normalized}", endpoint_class="entity"
        )
        page = parse_page(response.text, self.source)
        rows = [r for r in page.rows if normalize_doi(str(r.get("doi", ""))) == normalized]
        if not rows:
            raise SourceNotFound(self.source, f"{self.server} has no preprint {normalized}")
        preprint = parse_preprint(self.source, normalized, rows)
        record_id = await self._records.save(
            self.source, normalized, "details", {"collection": rows}, response.fetched_at
        )
        return FetchedPreprint(preprint, record_id, response.fetched_at, response.cache_hit)

    async def details_page(self, start: date, end: date, cursor: int = 0) -> Page:
        response = await self._client.get(
            f"{API_URL}/details/{self.server}/{start.isoformat()}/{end.isoformat()}/{cursor}",
            endpoint_class="search",
        )
        return parse_page(response.text, self.source, cursor)

    async def details_in_interval(
        self, start: date, end: date, max_rows: int = 10_000
    ) -> list[Mapping[str, Any]]:
        """Every version posted in [start, end] (inclusive days), following the cursor."""
        rows: list[Mapping[str, Any]] = []
        cursor: int | None = 0
        while cursor is not None and len(rows) < max_rows:
            page = await self.details_page(start, end, cursor)
            rows.extend(page.rows)
            cursor = page.next_cursor
        return rows[:max_rows]

    async def publications(self, start: date, end: date, cursor: int = 0) -> list[PublicationLink]:
        links: list[PublicationLink] = []
        next_cursor: int | None = cursor
        while next_cursor is not None:
            response = await self._client.get(
                f"{API_URL}/pubs/{self.server}/{start.isoformat()}/{end.isoformat()}/{next_cursor}",
                endpoint_class="search",
            )
            page = parse_page(response.text, self.source, next_cursor)
            links.extend(parse_link(r) for r in page.rows)
            next_cursor = page.next_cursor
        return links


def parse_page(text: str, source: SourceName, cursor: int = 0) -> Page:
    try:
        body = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceError(source, "bioRxiv/medRxiv returned a response that is not JSON") from exc
    messages = body.get("messages") or [{}]
    status = str(messages[0].get("status", ""))
    rows = list(body.get("collection") or [])
    if status == NO_POSTS:
        return Page([], 0, None)
    if status != "ok":
        raise SourceError(source, f"bioRxiv/medRxiv reported: {status or 'no status'}")
    total = int(messages[0].get("total") or len(rows))
    count = int(messages[0].get("count") or len(rows))
    following = cursor + count
    return Page(rows, total, following if count and following < total else None)


def _day(text: object) -> date | None:
    if not text or text == "NA":
        return None
    return date.fromisoformat(str(text))


def parse_preprint(source: SourceName, doi: str, rows: list[Mapping[str, Any]]) -> ServerPreprint:
    versions = sorted(
        (
            PreprintVersion(
                version=int(r["version"]),
                posted=date.fromisoformat(str(r["date"])),
                title=" ".join(str(r.get("title", "")).split()),
                authors=tuple(a.strip() for a in str(r.get("authors", "")).split(";") if a.strip()),
                category=r.get("category"),
                license=r.get("license"),
                abstract=" ".join(str(r.get("abstract", "")).split()) or None,
                type=r.get("type"),
                published_doi=(
                    normalize_doi(str(r["published"]))
                    if r.get("published") and r.get("published") != "NA"
                    else None
                ),
                jats_url=r.get("jatsxml"),
            )
            for r in rows
        ),
        key=lambda v: v.version,
    )
    return ServerPreprint(source, doi, tuple(versions), list(rows))


def parse_link(row: Mapping[str, Any]) -> PublicationLink:
    return PublicationLink(
        preprint_doi=normalize_doi(str(row["preprint_doi"])),
        published_doi=normalize_doi(str(row["published_doi"])),
        published_journal=row.get("published_journal"),
        preprint_date=_day(row.get("preprint_date")),
        published_date=_day(row.get("published_date")),
        raw=row,
    )


def posted_at(day: date) -> datetime:
    """Date-only values are stored at 00:00 UTC with day precision (D23)."""
    return datetime(day.year, day.month, day.day, tzinfo=UTC)
