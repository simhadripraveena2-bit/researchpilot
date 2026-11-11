"""arXiv API client (export.arxiv.org/api/query, Atom 1.0).

Verified behaviour (2026-11-11; see docs/integrations/ARXIV.md):

* ``<published>`` is the **v1 submission** timestamp (UTC), not the public announcement.
* ``<updated>`` is the submission timestamp of the **latest** version (or of the version
  asked for with ``id_list=<id>vN``). It is *not* a metadata-change date.
* The entry ``<id>`` carries the latest version (``.../abs/1706.03762v7``).
* Version history is not listed; per-version timestamps need one query per version.
* An unknown ID returns HTTP 200 with **zero entries**.
* Errors come back as HTTP 200 with a single entry whose ``<id>`` is
  ``https://arxiv.org/api/errors``. Any **old-style ID with a version suffix**
  (``hep-th/9711200v2``), alone or in a list, fails: with that error entry when the ``/`` is
  literal, with HTTP 500 when it is percent-encoded (as httpx sends parameters). Old-style
  IDs are therefore always queried without a version.
* ``<arxiv:doi>`` and ``<arxiv:journal_ref>`` are author-supplied links to a published
  version (decisive evidence for the Version Matcher, D29).

Terms of use: at most one request every 3 seconds, one connection at a time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from xml.etree.ElementTree import Element, tostring

import defusedxml.ElementTree as SafeET

from researchpilot.domain.enums import SourceName
from researchpilot.domain.identifiers import Identifier, IdentifierScheme, normalize_arxiv
from researchpilot.integrations.base import (
    SourceClient,
    SourceError,
    SourceNotFound,
    SourcePolicy,
    SourceRecordStore,
)

API_URL = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
ERROR_ENTRY_ID = "https://arxiv.org/api/errors"
MAX_IDS_PER_REQUEST = 50

ARXIV_POLICY = SourcePolicy(
    source=SourceName.ARXIV_API,
    min_interval_seconds=3.0,
    cache_ttl={"entity": timedelta(hours=12), "search": timedelta(hours=1)},
)


@dataclass(frozen=True)
class ArxivAuthor:
    name: str
    affiliations: tuple[str, ...]


@dataclass(frozen=True)
class ArxivEntry:
    arxiv_id: str
    latest_version: int
    title: str
    abstract: str
    authors: tuple[ArxivAuthor, ...]
    submitted_v1: datetime  # <published>
    submitted_latest: datetime  # <updated>
    primary_category: str | None
    categories: tuple[str, ...]
    doi: str | None  # author-supplied DOI of a published version
    journal_ref: str | None
    comment: str | None
    abs_url: str
    pdf_url: str | None
    entry_xml: str

    @property
    def versioned_id(self) -> str:
        return f"{self.arxiv_id}v{self.latest_version}"


@dataclass(frozen=True)
class FetchedEntry:
    entry: ArxivEntry
    source_record_id: uuid.UUID
    fetched_at: datetime
    cache_hit: bool


class ArxivClient:
    def __init__(self, client: SourceClient, records: SourceRecordStore) -> None:
        if client.source is not SourceName.ARXIV_API:
            raise ValueError("ArxivClient needs a SourceClient configured for arxiv_api")
        self._client = client
        self._records = records

    async def fetch(self, identifier: Identifier) -> FetchedEntry:
        """Latest metadata of one paper; raises ``SourceNotFound`` if arXiv has no such ID."""
        if identifier.scheme is not IdentifierScheme.ARXIV:
            raise ValueError("not an arXiv identifier")
        found = await self.fetch_many([identifier.value])
        if identifier.value not in found:
            raise SourceNotFound(SourceName.ARXIV_API, f"arXiv has no paper {identifier.value}")
        return found[identifier.value]

    async def fetch_many(self, arxiv_ids: list[str]) -> dict[str, FetchedEntry]:
        """Latest metadata for up to ``MAX_IDS_PER_REQUEST`` unversioned IDs per request."""
        results: dict[str, FetchedEntry] = {}
        ids = list(dict.fromkeys(normalize_arxiv(i)[0] for i in arxiv_ids))
        for start in range(0, len(ids), MAX_IDS_PER_REQUEST):
            chunk = ids[start : start + MAX_IDS_PER_REQUEST]
            response = await self._client.get(
                API_URL,
                params={"id_list": ",".join(chunk), "max_results": len(chunk)},
                endpoint_class="entity",
            )
            for entry in parse_feed(response.text):
                record_id = await self._records.save(
                    SourceName.ARXIV_API,
                    entry.versioned_id,
                    "api/query",
                    {"entry_xml": entry.entry_xml},
                    response.fetched_at,
                )
                results[entry.arxiv_id] = FetchedEntry(
                    entry, record_id, response.fetched_at, response.cache_hit
                )
        return results


def parse_feed(xml_text: str) -> list[ArxivEntry]:
    root = SafeET.fromstring(xml_text)
    entries = root.findall(f"{ATOM}entry")
    errors = [e for e in entries if _text(e, f"{ATOM}id") == ERROR_ENTRY_ID]
    if errors:
        message = _text(errors[0], f"{ATOM}summary")
        raise SourceError(SourceName.ARXIV_API, f"arXiv reported an error: {message}")
    return [parse_entry(e) for e in entries]


def parse_entry(entry: Element) -> ArxivEntry:
    abs_id = _required(entry, f"{ATOM}id")
    tail = abs_id.split("/abs/", 1)[-1]
    arxiv_id, version = normalize_arxiv(tail)
    pdf_url = next(
        (link.get("href") for link in entry.findall(f"{ATOM}link") if link.get("title") == "pdf"),
        None,
    )
    primary = entry.find(f"{ARXIV}primary_category")
    return ArxivEntry(
        arxiv_id=arxiv_id,
        latest_version=version or 1,
        title=_collapse(_required(entry, f"{ATOM}title")),
        abstract=_collapse(_text(entry, f"{ATOM}summary")),
        authors=tuple(
            ArxivAuthor(
                name=_collapse(_text(a, f"{ATOM}name")),
                affiliations=tuple(
                    _collapse(x.text or "") for x in a.findall(f"{ARXIV}affiliation")
                ),
            )
            for a in entry.findall(f"{ATOM}author")
        ),
        submitted_v1=_timestamp(_required(entry, f"{ATOM}published")),
        submitted_latest=_timestamp(_required(entry, f"{ATOM}updated")),
        primary_category=primary.get("term") if primary is not None else None,
        categories=tuple(
            c.get("term", "") for c in entry.findall(f"{ATOM}category") if c.get("term")
        ),
        doi=_text(entry, f"{ARXIV}doi") or None,
        journal_ref=_collapse(_text(entry, f"{ARXIV}journal_ref")) or None,
        comment=_collapse(_text(entry, f"{ARXIV}comment")) or None,
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=pdf_url,
        entry_xml=tostring(entry, encoding="unicode"),
    )


def _text(element: Element, tag: str) -> str:
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _required(element: Element, tag: str) -> str:
    value = _text(element, tag)
    if not value:
        raise SourceError(SourceName.ARXIV_API, f"arXiv entry without {tag.split('}')[-1]}")
    return value


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _timestamp(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise SourceError(SourceName.ARXIV_API, f"timestamp without time zone: {text}")
    return value
