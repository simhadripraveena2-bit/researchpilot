"""OpenAlex client (api.openalex.org): work lookups, budgeted search, capability switch (D24).

Verified behaviour (2026-11-11; see docs/integrations/OPENALEX.md):

* Every response carries usage headers: ``x-ratelimit-cost-usd`` (cost of this request),
  ``x-ratelimit-limit-usd`` / ``x-ratelimit-remaining-usd`` (daily budget), ``x-ratelimit-reset``
  (seconds). Without an API key the budget ($0.10/day) is **shared by every client on the
  network's IP address**.
* Single-work lookups (``/works/{id}``, ``/works/doi:{doi}``) cost $0; list/filter queries cost
  credits. With the budget used up, list queries return **429** with
  ``x-ratelimit-credits-required``, ``Retry-After`` = seconds to midnight UTC, and a JSON
  ``error`` - this is a budget stop, not load, and is never retried.
* Unknown work: HTTP 404 with an HTML body.
* ``publication_date`` is always ``YYYY-MM-DD``; missing parts are filled with ``01``
  (CVPR 2016: ``2016-06-01`` where Crossref deposits only ``2016-06``; ATMP 1998:
  ``1998-01-01``). ``MM-01`` is therefore stored with month precision, ``01-01`` with year.
* OpenAlex can merge versions into one work: the bioRxiv preprint and its eLife article are
  one work (W4372330081) whose ``publication_date`` (2023-05-05) is neither the preprint
  posting (2022-10-22) nor the journal date (2024-06-03). Its dates are secondary claims with
  unknown upstream; "both identifiers on one work" is strong, never decisive, evidence.
* ``created_date`` (first indexed) and ``updated_date`` are returned by basic lookups; the
  *filters* on them for finding newly indexed works need the premium capability.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import httpx

from researchpilot.core.clock import Clock, SystemClock
from researchpilot.domain.enums import DatePrecision, SourceName
from researchpilot.domain.identifiers import (
    Identifier,
    IdentifierScheme,
    InvalidIdentifier,
    normalize_doi,
    parse_identifier,
)
from researchpilot.integrations.base import (
    SourceBudgetExhausted,
    SourceClient,
    SourceError,
    SourcePolicy,
    SourceRecordStore,
)

API_URL = "https://api.openalex.org"
Capabilities = Literal["basic", "premium"]

OPENALEX_POLICY = SourcePolicy(
    source=SourceName.OPENALEX,
    min_interval_seconds=0.1,  # documented limit: 10 requests per second
    cache_ttl={"entity": timedelta(days=7), "search": timedelta(hours=1)},
)


class OpenAlexBudget:
    """Tracks OpenAlex usage from response headers plus our own daily cap.

    Entity lookups (cost $0) are always allowed; metered requests stop when OpenAlex reports
    no remaining budget (until its reset time) or when our own spend reaches the cap.
    """

    def __init__(self, daily_cap_usd: float, clock: Clock | None = None) -> None:
        self.daily_cap_usd = daily_cap_usd
        self._clock = clock or SystemClock()
        self.spent_usd = 0.0
        self.remaining_usd: float | None = None
        self.blocked_until: datetime | None = None
        self._day = self._clock.now().date()

    def _roll(self) -> None:
        today = self._clock.now().date()
        if today != self._day:
            self._day, self.spent_usd = today, 0.0

    def check(self, endpoint_class: str) -> None:
        self._roll()
        if endpoint_class == "entity":
            return
        now = self._clock.now()
        if self.blocked_until is not None and now < self.blocked_until:
            raise SourceBudgetExhausted(
                SourceName.OPENALEX,
                f"OpenAlex usage budget is used up until {self.blocked_until.isoformat()}",
                upstream_status=429,
            )
        if self.spent_usd >= self.daily_cap_usd:
            raise SourceBudgetExhausted(
                SourceName.OPENALEX, "the configured daily OpenAlex budget is used up"
            )

    def observe(self, endpoint_class: str, response: httpx.Response) -> None:
        headers = response.headers
        cost = _float(headers.get("x-ratelimit-cost-usd"))
        if cost:
            self.spent_usd += cost
        remaining = _float(headers.get("x-ratelimit-remaining-usd"))
        if remaining is not None:
            self.remaining_usd = remaining
        needs = headers.get("x-ratelimit-credits-required") or headers.get(
            "x-ratelimit-cost-required-usd"
        )
        if response.status_code == 429 and needs is not None:
            reset = _float(headers.get("x-ratelimit-reset") or headers.get("retry-after"))
            self.blocked_until = self._clock.now() + timedelta(seconds=reset or 3600)


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except ValueError:
        return None


@dataclass(frozen=True)
class OpenAlexWork:
    id: str  # W...
    doi: str | None
    title: str
    type: str | None
    publication_date: str | None
    publication_year: int | None
    created_date: str | None
    updated_date: str | None
    authors: tuple[str, ...]
    listed_identifiers: tuple[Identifier, ...]  # every DOI/arXiv/PMID the work lists
    indexed_in: tuple[str, ...]
    raw: Mapping[str, Any]

    def reported_date(self) -> tuple[datetime, DatePrecision] | None:
        """``publication_date`` with honest precision (day 01 = month precision)."""
        if not self.publication_date:
            return None
        day = date.fromisoformat(self.publication_date)
        if (day.month, day.day) == (1, 1):
            precision = DatePrecision.YEAR  # year-only dates come back as YYYY-01-01
        elif day.day == 1:
            precision = DatePrecision.MONTH  # month-only dates come back as YYYY-MM-01
        else:
            precision = DatePrecision.DAY
        return datetime(day.year, day.month, day.day, tzinfo=UTC), precision


@dataclass(frozen=True)
class FetchedOpenAlexWork:
    work: OpenAlexWork
    source_record_id: uuid.UUID
    fetched_at: datetime
    cache_hit: bool


class OpenAlexClient:
    def __init__(
        self,
        client: SourceClient,
        records: SourceRecordStore,
        capabilities: Capabilities = "basic",
    ) -> None:
        if client.source is not SourceName.OPENALEX:
            raise ValueError("OpenAlexClient needs a SourceClient configured for openalex")
        self._client = client
        self._records = records
        self.capabilities = capabilities

    async def fetch(self, identifier: Identifier) -> FetchedOpenAlexWork:
        """One work (free single-work lookup); ``SourceNotFound`` if OpenAlex has none."""
        response = await self._client.get(
            f"{API_URL}/works/{work_path(identifier)}", endpoint_class="entity"
        )
        work = parse_work(_json(response.text))
        record_id = await self._records.save(
            SourceName.OPENALEX, work.id, "works", dict(work.raw), response.fetched_at
        )
        return FetchedOpenAlexWork(work, record_id, response.fetched_at, response.cache_hit)

    def search_params(
        self,
        *,
        search: str | None,
        published_from: date | None = None,
        indexed_from: date | None = None,
        per_page: int = 50,
        cursor: str = "*",
    ) -> dict[str, Any]:
        """Search parameters for both capability paths. ``indexed_from`` (newly indexed works)
        needs the premium ``from_created_date`` filter; on basic access it is refused rather
        than silently replaced by a publication-date filter."""
        filters: list[str] = []
        if published_from:
            filters.append(f"from_publication_date:{published_from.isoformat()}")
        if indexed_from:
            if self.capabilities != "premium":
                raise SourceError(
                    SourceName.OPENALEX,
                    "finding newly indexed works needs the OpenAlex premium capability",
                )
            filters.append(f"from_created_date:{indexed_from.isoformat()}")
        params: dict[str, Any] = {"per-page": max(1, min(per_page, 200)), "cursor": cursor}
        if search:
            params["search"] = search
        if filters:
            params["filter"] = ",".join(filters)
        return params

    async def search_page(self, **kwargs: Any) -> tuple[list[OpenAlexWork], str | None]:
        """One metered page (budget-checked); returns works and the next cursor."""
        response = await self._client.get(
            f"{API_URL}/works", params=self.search_params(**kwargs), endpoint_class="search"
        )
        body = _json(response.text)
        works = [parse_work(item) for item in body.get("results", [])]
        for w in works:
            await self._records.save(
                SourceName.OPENALEX, w.id, "works", dict(w.raw), response.fetched_at
            )
        return works, (body.get("meta") or {}).get("next_cursor")


def work_path(identifier: Identifier) -> str:
    match identifier.scheme:
        case IdentifierScheme.OPENALEX:
            return identifier.value
        case IdentifierScheme.DOI:
            return f"doi:{identifier.value}"
        case IdentifierScheme.ARXIV:
            return f"doi:10.48550/arxiv.{identifier.value}"
        case IdentifierScheme.PMID:
            return f"pmid:{identifier.value}"
        case _:
            raise SourceError(SourceName.OPENALEX, f"OpenAlex cannot look up {identifier.scheme}")


def _json(text: str) -> dict[str, Any]:
    try:
        body: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceError(
            SourceName.OPENALEX, "OpenAlex returned a response that is not JSON"
        ) from exc
    return body


_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/([^\s?#]+?)(?:v\d+)?(?:\.pdf)?$", re.IGNORECASE)


def _identifier_from_url(url: str | None) -> Identifier | None:
    if not url:
        return None
    try:
        if "doi.org/" in url:
            doi = normalize_doi(url)
            return parse_identifier(f"doi:{doi}")
        match = _ARXIV_URL.search(url)
        if match:
            return parse_identifier(f"arXiv:{match.group(1)}")
        if "pubmed.ncbi.nlm.nih.gov/" in url:
            return parse_identifier(url)
    except InvalidIdentifier:
        return None
    return None


def parse_work(raw: Mapping[str, Any]) -> OpenAlexWork:
    work_id = str(raw.get("id", "")).rsplit("/", 1)[-1]
    if not work_id.startswith("W"):
        raise SourceError(SourceName.OPENALEX, "OpenAlex record without a work id")
    listed: list[Identifier] = []
    urls = [raw.get("doi")]
    for location in raw.get("locations") or []:
        urls += [location.get("landing_page_url"), location.get("pdf_url")]
    ids = raw.get("ids") or {}
    urls += [ids.get("doi"), ids.get("pmid")]
    for url in urls:
        found = _identifier_from_url(url)
        if found is not None:
            # An arXiv DataCite DOI is the arXiv ID.
            if found.scheme is IdentifierScheme.DOI and found.value.startswith("10.48550/arxiv."):
                found = parse_identifier(f"arXiv:{found.value.removeprefix('10.48550/arxiv.')}")
            plain = Identifier(found.scheme, found.value)
            if plain not in listed:
                listed.append(plain)
    doi = raw.get("doi")
    return OpenAlexWork(
        id=work_id,
        doi=normalize_doi(doi) if doi else None,
        title=" ".join(str(raw.get("title") or raw.get("display_name") or "").split()),
        type=raw.get("type"),
        publication_date=raw.get("publication_date"),
        publication_year=raw.get("publication_year"),
        created_date=raw.get("created_date"),
        updated_date=raw.get("updated_date"),
        authors=tuple(
            str((a.get("author") or {}).get("display_name") or a.get("raw_author_name") or "")
            for a in raw.get("authorships") or []
        ),
        listed_identifiers=tuple(listed),
        indexed_in=tuple(raw.get("indexed_in") or ()),
        raw=raw,
    )
