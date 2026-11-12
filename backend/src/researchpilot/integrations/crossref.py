"""Crossref REST API client (api.crossref.org) - DOI lookups and cursor-paginated search.

Verified behaviour (2026-11-11; see docs/integrations/CROSSREF.md):

* Rate limit headers on every response: public pool ``x-rate-limit-limit: 5``,
  ``x-rate-limit-interval: 1s``, ``x-concurrency-limit: 1``. We stay below (1 request per
  0.25 s, one at a time per process).
* Unknown DOI: HTTP 404 with the plain-text body ``Resource not found.``
* Dates are ``date-parts`` of length 3, 2 or 1 (day, month or year precision); only
  ``created``/``deposited``/``indexed`` also carry a timestamp.
* ``issued`` is Crossref's derived earliest of the publication dates.
* ``relation`` links versions: ``has-preprint`` / ``is-preprint-of`` (each with
  ``asserted-by: subject|object``), ``is-reply-to``, ``is-same-as``, ``has-version``...
* bioRxiv/medRxiv DOIs (``10.1101/...``) are ``posted-content`` (subtype ``preprint``) with
  ``institution: [{name: bioRxiv}]``; their ``posted`` is the v1 posting date, and their
  ``accepted`` field tracks the latest preprint version - it is **not** a journal
  acceptance and is not recorded as one.
* Titles and abstracts may contain JATS/HTML markup (``<i>de novo</i>``).
* Notices are typed like ordinary articles (``journal-article``); only ``update-to``
  (on the notice: ``[{DOI, type: correction|retraction|..., source, updated}]``) and
  ``updated-by`` (on the original) identify them (verified on a correction and a retraction,
  2026-11-12).
* Search uses deep-paging cursors: ``cursor=*`` then ``next-cursor``; ``rows`` <= 1000.
"""

from __future__ import annotations

import html
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from researchpilot.domain.enums import DatePrecision, SourceName
from researchpilot.domain.identifiers import InvalidIdentifier, normalize_doi
from researchpilot.integrations.base import (
    SourceClient,
    SourceError,
    SourcePolicy,
    SourceRecordStore,
)

API_URL = "https://api.crossref.org/works"
MAX_ROWS = 1000

CROSSREF_POLICY = SourcePolicy(
    source=SourceName.CROSSREF,
    min_interval_seconds=0.25,
    cache_ttl={"entity": timedelta(days=7), "search": timedelta(hours=1)},
)

DATE_FIELDS = (
    "posted",
    "published-online",
    "published-print",
    "issued",
    "accepted",
    "created",
    "deposited",
    "indexed",
)


@dataclass(frozen=True)
class PartialDate:
    """A Crossref date: always stored as UTC midnight of its first day, with precision."""

    value: datetime
    precision: DatePrecision
    parts: tuple[int, ...]


@dataclass(frozen=True)
class CrossrefAuthor:
    given: str | None
    family: str | None
    name: str  # display form
    orcid: str | None
    affiliations: tuple[str, ...]


@dataclass(frozen=True)
class CrossrefRelation:
    type: str
    id: str
    id_type: str
    asserted_by: str | None


@dataclass(frozen=True)
class CrossrefUpdate:
    """A Crossref ``update-to`` / ``updated-by`` entry: a notice (correction, retraction,
    expression of concern...) and the work it is about."""

    doi: str
    type: str
    source: str | None
    date: PartialDate | None


@dataclass(frozen=True)
class CrossrefWork:
    doi: str
    type: str
    subtype: str | None
    title: str
    container_title: str | None
    publisher: str | None
    institution: str | None  # e.g. bioRxiv for posted-content
    authors: tuple[CrossrefAuthor, ...]
    dates: Mapping[str, PartialDate]
    relations: tuple[CrossrefRelation, ...]
    updates: tuple[CrossrefUpdate, ...]  # update-to: this record is a notice about these
    updated_by: tuple[CrossrefUpdate, ...]  # updated-by: notices about this record
    abstract: str | None
    url: str | None
    license_url: str | None
    raw: Mapping[str, Any]

    @property
    def is_preprint(self) -> bool:
        return self.type == "posted-content" and (self.subtype in (None, "preprint"))

    def related_dois(self, *types: str) -> list[str]:
        out: list[str] = []
        for rel in self.relations:
            if rel.type in types and rel.id_type == "doi":
                try:
                    out.append(normalize_doi(rel.id))
                except InvalidIdentifier:
                    continue
        return list(dict.fromkeys(out))


@dataclass(frozen=True)
class FetchedWork:
    work: CrossrefWork
    source_record_id: uuid.UUID
    fetched_at: datetime
    cache_hit: bool


@dataclass(frozen=True)
class SearchPage:
    works: list[FetchedWork]
    total_results: int
    next_cursor: str | None


class CrossrefClient:
    def __init__(self, client: SourceClient, records: SourceRecordStore) -> None:
        if client.source is not SourceName.CROSSREF:
            raise ValueError("CrossrefClient needs a SourceClient configured for crossref")
        self._client = client
        self._records = records

    async def fetch(self, doi: str) -> FetchedWork:
        """One work by DOI; raises ``SourceNotFound`` for unknown DOIs (HTTP 404)."""
        normalized = normalize_doi(doi)
        response = await self._client.get(
            f"{API_URL}/{quote(normalized, safe='/:()')}", endpoint_class="entity"
        )
        message = _message(response.text, "work")
        return await self._store(parse_work(message), response.fetched_at, response.cache_hit)

    async def search(
        self,
        *,
        query: str | None = None,
        filters: Mapping[str, str] | None = None,
        max_results: int = 100,
        rows: int = 100,
    ) -> list[FetchedWork]:
        """All results up to ``max_results``, following ``next-cursor`` page by page."""
        results: list[FetchedWork] = []
        cursor: str | None = "*"
        while cursor and len(results) < max_results:
            page = await self.search_page(
                query=query,
                filters=filters,
                rows=min(rows, max_results - len(results)),
                cursor=cursor,
            )
            results.extend(page.works)
            if not page.works:
                break
            cursor = page.next_cursor
        return results[:max_results]

    async def search_page(
        self,
        *,
        query: str | None,
        filters: Mapping[str, str] | None,
        rows: int,
        cursor: str,
    ) -> SearchPage:
        params: dict[str, Any] = {"rows": max(1, min(rows, MAX_ROWS)), "cursor": cursor}
        if query:
            params["query.bibliographic"] = query
        if filters:
            params["filter"] = ",".join(f"{k}:{v}" for k, v in filters.items())
        response = await self._client.get(API_URL, params=params, endpoint_class="search")
        message = _message(response.text, "work-list")
        works = [
            await self._store(parse_work(item), response.fetched_at, response.cache_hit)
            for item in message.get("items", [])
        ]
        return SearchPage(
            works=works,
            total_results=int(message.get("total-results", 0)),
            next_cursor=message.get("next-cursor"),
        )

    async def topic_search(self, query: str, *, rows: int = 20) -> SearchPage:
        """First page of a relevance-ranked topic search (``query``, ``sort=relevance``).

        Verified 2026-11-12: with ``cursor=*`` Crossref ignores relevance (the response
        reports ``search-terms: null`` and returns unrelated works), so topic searches send
        no cursor; deep paging is not needed for a relevance-ranked first page.
        """
        params = {"query": query, "rows": max(1, min(rows, MAX_ROWS)), "sort": "relevance"}
        response = await self._client.get(API_URL, params=params, endpoint_class="search")
        message = _message(response.text, "work-list")
        works = [
            await self._store(parse_work(item), response.fetched_at, response.cache_hit)
            for item in message.get("items", [])
        ]
        return SearchPage(
            works=works,
            total_results=int(message.get("total-results", 0)),
            next_cursor=None,
        )

    async def _store(
        self, work: CrossrefWork, fetched_at: datetime, cache_hit: bool
    ) -> FetchedWork:
        record_id = await self._records.save(
            SourceName.CROSSREF, work.doi, "works", dict(work.raw), fetched_at
        )
        return FetchedWork(work, record_id, fetched_at, cache_hit)


def _message(text: str, expected_type: str) -> dict[str, Any]:
    try:
        body = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceError(
            SourceName.CROSSREF, "Crossref returned a response that is not JSON"
        ) from exc
    if body.get("status") != "ok" or body.get("message-type") != expected_type:
        raise SourceError(
            SourceName.CROSSREF, f"unexpected Crossref response ({body.get('status')})"
        )
    message: dict[str, Any] = body["message"]
    return message


_TAGS = re.compile(r"<[^>]+>")


def clean_markup(text: str | None) -> str | None:
    """Removes JATS/HTML tags and entities; collapses whitespace."""
    if not text:
        return None
    cleaned = " ".join(html.unescape(_TAGS.sub(" ", text)).split())
    cleaned = re.sub(r"^Abstract\s+", "", cleaned)
    return cleaned or None


def parse_date(field: Mapping[str, Any] | None) -> PartialDate | None:
    if not field:
        return None
    parts_list = field.get("date-parts") or [[]]
    parts = tuple(int(p) for p in (parts_list[0] or []) if p is not None)
    if not parts:
        return None
    precision = {3: DatePrecision.DAY, 2: DatePrecision.MONTH, 1: DatePrecision.YEAR}[
        min(len(parts), 3)
    ]
    year, month, day = (*parts, 1, 1)[:3]
    return PartialDate(datetime(year, month, day, tzinfo=UTC), precision, parts[:3])


def parse_work(message: Mapping[str, Any]) -> CrossrefWork:
    authors = []
    for a in message.get("author", []) or []:
        given, family = a.get("given"), a.get("family")
        name = " ".join(x for x in (given, family) if x) or a.get("name") or ""
        orcid = a.get("ORCID")
        authors.append(
            CrossrefAuthor(
                given=given,
                family=family,
                name=name,
                orcid=orcid.rsplit("/", 1)[-1] if orcid else None,
                affiliations=tuple(x.get("name", "") for x in a.get("affiliation", []) or []),
            )
        )
    relations = [
        CrossrefRelation(
            rel_type, str(r.get("id", "")), str(r.get("id-type", "")), r.get("asserted-by")
        )
        for rel_type, items in (message.get("relation") or {}).items()
        for r in items or []
    ]
    dates = {f: d for f in DATE_FIELDS if (d := parse_date(message.get(f))) is not None}
    institution = next(
        (i.get("name") for i in message.get("institution", []) or [] if i.get("name")), None
    )
    licenses = message.get("license") or []

    def updates(field: str) -> tuple[CrossrefUpdate, ...]:
        out: list[CrossrefUpdate] = []
        for u in message.get(field) or []:
            try:
                doi = normalize_doi(str(u.get("DOI", "")))
            except InvalidIdentifier:
                continue
            out.append(
                CrossrefUpdate(
                    doi,
                    str(u.get("type", "")).lower(),
                    u.get("source"),
                    parse_date(u.get("updated")),
                )
            )
        return tuple(out)

    return CrossrefWork(
        doi=normalize_doi(message["DOI"]),
        type=str(message.get("type", "")),
        subtype=message.get("subtype"),
        title=clean_markup((message.get("title") or [""])[0]) or "",
        container_title=clean_markup((message.get("container-title") or [None])[0]),
        publisher=message.get("publisher"),
        institution=institution,
        authors=tuple(authors),
        dates=dates,
        relations=tuple(relations),
        updates=updates("update-to"),
        updated_by=updates("updated-by"),
        abstract=clean_markup(message.get("abstract")),
        url=message.get("URL"),
        license_url=licenses[0].get("URL") if licenses else None,
        raw=message,
    )
