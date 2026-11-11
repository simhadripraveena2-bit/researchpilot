"""Semantic Scholar Graph API client (api.semanticscholar.org/graph/v1).

Verified behaviour (2026-11-11; see docs/integrations/SEMANTIC_SCHOLAR.md):

* Without an API key, requests from this environment were refused every time with HTTP 429,
  JSON ``{"message": "Too Many Requests. ...", "code": "429"}`` and **no** ``Retry-After``
  (``x-amzn-errortype: TooManyRequestsException``). The unauthenticated pool is shared by
  all clients. The client retries with jittered backoff and then reports the source as
  unavailable; adding a paper never depends on it.
* With a key (``S2_API_KEY``), the key is sent as ``x-api-key``; keys default to one request
  per second.

Not verified live (no key available): the success responses. The parser follows the
published Graph API schema (``paperId``, ``corpusId``, ``externalIds`` with ``DOI``,
``ArXiv``, ``PubMed``, ``PubMedCentral``, ``CorpusId``, ``publicationDate`` as
``YYYY-MM-DD`` or null, ``authors[].name``), and the test fixture for it is marked as
constructed, not recorded.

``externalIds`` listing a DOI and an arXiv ID on one record is *strong* Version Matcher
evidence (S2 merges versions), never decisive. ``publicationDate`` is a secondary claim with
unknown upstream.
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

S2_POLICY = SourcePolicy(
    source=SourceName.SEMANTIC_SCHOLAR,
    min_interval_seconds=1.0,  # API-key default: 1 request per second
    max_attempts=3,
    backoff_base_seconds=2.0,
    cache_ttl={"entity": timedelta(days=7), "search": timedelta(hours=1)},
)

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
