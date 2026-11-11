"""Semantic Scholar Graph API client (api.semanticscholar.org/graph/v1).

Verified behaviour (2026-11-11; see docs/integrations/SEMANTIC_SCHOLAR.md):

* **With an API key** (``S2_API_KEY``, sent as ``x-api-key``): the approved limit is
  1 request per second **cumulative across all endpoints**. Requests closer than that get
  HTTP 429 ``{"message": "Too Many Requests...", "code": "429"}``,
  ``x-amzn-errortype: TooManyRequestsException`` and **no** ``Retry-After``; occasional 429s
  also occurred with 1.5-3 s spacing, and requests recovered after a few seconds.
* **Without a key**: every request from this environment got the same 429.
* Unknown paper: HTTP 404 ``{"error": "Paper with id ... not found"}``.
* ``/paper/search`` and ``/paper/{id}/references`` page with ``offset`` / ``limit`` and return
  ``next`` (absent on the last page); search also returns ``total``.

Every endpoint goes through one ``SourceClient`` whose limiter key is
``semantic_scholar``: a single slot sequence, shared by the API and worker processes through
Postgres, with a conservative minimum interval of 1.25 s. A 429 defers that shared slot for
every process (``RateLimiter.defer``) by ``Retry-After`` when sent, else by jittered
exponential backoff.

``externalIds`` listing a DOI and an arXiv ID on one record is *strong* Version Matcher
evidence (S2 merges versions), never decisive. ``publicationDate`` is a secondary claim with
unknown upstream.

The API key is never logged or put in error messages: it is a ``SecretStr`` setting, sent
only as a request header, and ``SourceClient`` logs URLs and statuses only.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from researchpilot.domain.enums import DatePrecision, SourceName
from researchpilot.domain.identifiers import (
    Identifier,
    IdentifierScheme,
    InvalidIdentifier,
    parse_identifier,
)
from researchpilot.integrations.base import (
    SourceClient,
    SourceError,
    SourcePolicy,
    SourceRecordStore,
)

API_URL = "https://api.semanticscholar.org/graph/v1"
FIELDS = "paperId,corpusId,externalIds,title,year,publicationDate,venue,publicationTypes,authors"

S2_MIN_INTERVAL_SECONDS = 1.25  # approved: 1 request/s across all endpoints; kept below it

S2_POLICY = SourcePolicy(
    source=SourceName.SEMANTIC_SCHOLAR,
    min_interval_seconds=S2_MIN_INTERVAL_SECONDS,
    rate_limit_key=SourceName.SEMANTIC_SCHOLAR,  # one budget for every endpoint
    max_attempts=4,
    backoff_base_seconds=2.0,
    backoff_max_seconds=30.0,
    breaker_threshold=3,
    cache_ttl={
        "entity": timedelta(days=7),
        "search": timedelta(hours=1),
        "references": timedelta(days=1),
    },
)
REFERENCE_FIELDS = "paperId,externalIds,title,year"

_EXTERNAL = {
    "DOI": "doi",
    "ArXiv": "arXiv",
    "PubMed": "PMID",
    "PubMedCentral": "PMCID",
    "CorpusId": "CorpusId",
}


@dataclass(frozen=True)
class S2Paper:
    paper_id: str
    corpus_id: str | None
    title: str
    publication_date: date | None
    year: int | None
    authors: tuple[str, ...]
    listed_identifiers: tuple[Identifier, ...]
    raw: Mapping[str, Any]

    def reported_date(self) -> tuple[datetime, DatePrecision] | None:
        if self.publication_date is None:
            return None
        d = self.publication_date
        return datetime(d.year, d.month, d.day, tzinfo=UTC), DatePrecision.DAY


@dataclass(frozen=True)
class FetchedS2Paper:
    paper: S2Paper
    source_record_id: uuid.UUID
    fetched_at: datetime
    cache_hit: bool


class SemanticScholarClient:
    def __init__(self, client: SourceClient, records: SourceRecordStore) -> None:
        if client.source is not SourceName.SEMANTIC_SCHOLAR:
            raise ValueError("SemanticScholarClient needs a semantic_scholar SourceClient")
        self._client = client
        self._records = records

    async def fetch(self, identifier: Identifier) -> FetchedS2Paper:
        response = await self._client.get(
            f"{API_URL}/paper/{paper_ref(identifier)}",
            params={"fields": FIELDS},
            endpoint_class="entity",
        )
        paper = parse_paper(_json(response.text))
        record_id = await self._records.save(
            SourceName.SEMANTIC_SCHOLAR,
            paper.paper_id,
            "paper",
            dict(paper.raw),
            response.fetched_at,
        )
        return FetchedS2Paper(paper, record_id, response.fetched_at, response.cache_hit)

    async def search(self, query: str, *, limit: int = 20, offset: int = 0) -> S2Page:
        """One page of relevance search (``/paper/search``)."""
        response = await self._client.get(
            f"{API_URL}/paper/search",
            params={
                "query": query,
                "limit": str(min(max(limit, 1), 100)),
                "offset": str(offset),
                "fields": FIELDS,
            },
            endpoint_class="search",
        )
        body = _json(response.text)
        rows, nxt = _page(body, None)
        return S2Page(
            [await self._store(r, response.fetched_at) for r in rows], body.get("total"), nxt
        )

    async def references(self, paper_id: str, *, limit: int = 100, offset: int = 0) -> S2Page:
        """One page of the papers a paper cites (``/paper/{id}/references``)."""
        response = await self._client.get(
            f"{API_URL}/paper/{paper_id}/references",
            params={
                "fields": REFERENCE_FIELDS,
                "limit": str(min(max(limit, 1), 1000)),
                "offset": str(offset),
            },
            endpoint_class="references",
        )
        rows, nxt = _page(_json(response.text), "citedPaper")
        return S2Page([parse_paper(r) for r in rows], None, nxt)

    async def _store(self, raw: Mapping[str, Any], fetched_at: datetime) -> S2Paper:
        paper = parse_paper(raw)
        await self._records.save(
            SourceName.SEMANTIC_SCHOLAR, paper.paper_id, "paper/search", dict(raw), fetched_at
        )
        return paper


@dataclass(frozen=True)
class S2Page:
    papers: list[S2Paper]
    total: int | None
    next_offset: int | None


def _page(body: Mapping[str, Any], key: str | None) -> tuple[list[Mapping[str, Any]], int | None]:
    items = [(row.get(key) if key else row) for row in body.get("data") or []]
    nxt = body.get("next")
    return [i for i in items if i and i.get("paperId")], int(nxt) if nxt is not None else None


def paper_ref(identifier: Identifier) -> str:
    match identifier.scheme:
        case IdentifierScheme.S2_PAPER:
            return identifier.value
        case IdentifierScheme.S2_CORPUS:
            return f"CorpusId:{identifier.value}"
        case IdentifierScheme.DOI:
            return f"DOI:{identifier.value}"
        case IdentifierScheme.ARXIV:
            return f"ARXIV:{identifier.value}"
        case IdentifierScheme.PMID:
            return f"PMID:{identifier.value}"
        case _:
            raise SourceError(
                SourceName.SEMANTIC_SCHOLAR, f"Semantic Scholar cannot look up {identifier.scheme}"
            )


def _json(text: str) -> dict[str, Any]:
    try:
        body: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceError(
            SourceName.SEMANTIC_SCHOLAR, "Semantic Scholar returned a response that is not JSON"
        ) from exc
    return body


def parse_paper(raw: Mapping[str, Any]) -> S2Paper:
    paper_id = str(raw.get("paperId") or "")
    if not paper_id:
        raise SourceError(SourceName.SEMANTIC_SCHOLAR, "Semantic Scholar record without paperId")
    listed: list[Identifier] = []
    for key, prefix in _EXTERNAL.items():
        value = (raw.get("externalIds") or {}).get(key)
        if value in (None, ""):
            continue
        try:
            found = parse_identifier(f"{prefix}:{value}")
        except InvalidIdentifier:
            continue
        if found.scheme is IdentifierScheme.DOI and found.value.startswith("10.48550/arxiv."):
            found = parse_identifier(f"arXiv:{found.value.removeprefix('10.48550/arxiv.')}")
        plain = Identifier(found.scheme, found.value)
        if plain not in listed:
            listed.append(plain)
    published = raw.get("publicationDate")
    corpus = raw.get("corpusId")
    return S2Paper(
        paper_id=paper_id.lower(),
        corpus_id=str(corpus) if corpus is not None else None,
        title=" ".join(str(raw.get("title") or "").split()),
        publication_date=date.fromisoformat(published) if published else None,
        year=raw.get("year"),
        authors=tuple(str(a.get("name") or "") for a in raw.get("authors") or []),
        listed_identifiers=tuple(listed),
        raw=raw,
    )
