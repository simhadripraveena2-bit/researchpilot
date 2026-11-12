"""Best-effort enrichment from aggregators (OpenAlex, Semantic Scholar).

Aggregators are never systems of record here. They contribute:

* their own identifiers (OpenAlex ``W…``, Semantic Scholar paper/corpus IDs);
* secondary date claims - ``reported_publication_date`` (upstream unknown: neither API
  exposes where the date came from), and OpenAlex ``created_date`` / ``updated_date`` as
  ``index_created`` / ``metadata_updated``;
* "same record lists these identifiers" links, which the Version Matcher treats as strong
  (not decisive) evidence, because both sources sometimes merge versions.

A failing or budget-limited source only reduces coverage; the result says which.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.domain.enums import (
    DateEvent,
    DatePrecision,
    ReportingSource,
    SourceName,
    UpstreamSource,
)
from researchpilot.domain.identifiers import Identifier, IdentifierScheme
from researchpilot.integrations.base import SourceBudgetExhausted, SourceError, SourceNotFound
from researchpilot.integrations.openalex import FetchedOpenAlexWork
from researchpilot.integrations.registry import Sources
from researchpilot.integrations.semantic_scholar import FetchedS2Paper
from researchpilot.services.dates.store import resolve_paper_dates
from researchpilot.services.matching.links import StatedLink, record_links
from researchpilot.services.papers.ingest import add_date

log = structlog.get_logger(__name__)

SAME_RECORD = "same-record-listing"


async def lookup_identifier(
    session: AsyncSession, paper_id: uuid.UUID
) -> tuple[uuid.UUID, Identifier] | None:
    """The work's best identifier for aggregator lookups: a published DOI, else a preprint."""
    row = (
        await session.execute(
            sa.text(
                "SELECT id, primary_identifier_scheme AS scheme, primary_identifier_value "
                "AS value FROM paper_manifestations WHERE paper_id = :p "
                "ORDER BY (kind = 'published') DESC, created_at LIMIT 1"
            ),
            {"p": paper_id},
        )
    ).first()
    if row is None:
        return None
    return row.id, Identifier(IdentifierScheme(row.scheme), row.value)


async def enrich_work(
    session: AsyncSession, sources: Sources, paper_id: uuid.UUID
) -> dict[str, str]:
    target = await lookup_identifier(session, paper_id)
    if target is None:
        return {}
    manifestation_id, identifier = target
    coverage: dict[str, str] = {}
    steps: list[tuple[str, Callable[[], Awaitable[None]]]] = [
        ("openalex", lambda: _openalex(session, sources, paper_id, manifestation_id, identifier)),
        (
            "semantic_scholar",
            lambda: _semantic_scholar(session, sources, paper_id, manifestation_id, identifier),
        ),
    ]
    for name, step in steps:
        try:
            async with session.begin_nested():
                await step()
            coverage[name] = "ok"
        except SourceNotFound:
            coverage[name] = "not_found"
        except SourceBudgetExhausted:
            coverage[name] = "budget_exhausted"
        except SourceError as exc:
            coverage[name] = "unavailable"
            log.warning("papers.enrichment_unavailable", source=name, detail=exc.detail)
    await resolve_paper_dates(session, paper_id, datetime.now(UTC))
    return coverage


async def _openalex(
    session: AsyncSession,
    sources: Sources,
    paper_id: uuid.UUID,
    manifestation_id: uuid.UUID,
    identifier: Identifier,
) -> None:
    await apply_openalex(
        session, paper_id, manifestation_id, identifier, await sources.openalex.fetch(identifier)
    )


async def apply_openalex(
    session: AsyncSession,
    paper_id: uuid.UUID,
    manifestation_id: uuid.UUID,
    identifier: Identifier,
    fetched: FetchedOpenAlexWork,
) -> None:
    """Attach an OpenAlex record (from a lookup or a search hit) to a manifestation:
    its id, secondary dates and the identifiers it lists. ``identifier`` is the one the
    record was found by (never recorded as a listing link to itself)."""
    work, record_id, at = fetched.work, fetched.source_record_id, fetched.fetched_at
    await _link_record(session, paper_id, manifestation_id, record_id)
    await _add_own_identifier(
        session,
        paper_id,
        manifestation_id,
        IdentifierScheme.OPENALEX,
        work.id,
        SourceName.OPENALEX,
        record_id,
    )
    evidence: dict[str, Any] = {"record": work.id, "indexed_in": list(work.indexed_in)}
    reported = work.reported_date()
    if reported:
        value, precision = reported
        await add_date(
            session,
            paper_id,
            manifestation_id,
            DateEvent.REPORTED_PUBLICATION_DATE,
            value,
            precision,
            is_primary=False,
            reporting=ReportingSource.OPENALEX,
            upstream=UpstreamSource.UNKNOWN,
            evidence={
                **evidence,
                "field": "publication_date",
                "raw": work.publication_date,
                **(
                    {"note": "day 01 treated as month precision"}
                    if precision is DatePrecision.MONTH
                    else {}
                ),
            },
            record_id=record_id,
            retrieved_at=at,
        )
    for field, event in (
        ("created_date", DateEvent.INDEX_CREATED),
        ("updated_date", DateEvent.METADATA_UPDATED),
    ):
        raw = getattr(work, field)
        if raw:
            stamp = datetime.fromisoformat(raw).replace(tzinfo=UTC)
            await add_date(
                session,
                paper_id,
                manifestation_id,
                event,
                stamp,
                DatePrecision.TIMESTAMP,
                is_primary=False,
                reporting=ReportingSource.OPENALEX,
                upstream=UpstreamSource.UNKNOWN,
                evidence={**evidence, "field": field},
                record_id=record_id,
                retrieved_at=at,
            )
    await _listing_links(
        session,
        paper_id,
        manifestation_id,
        SourceName.OPENALEX,
        work.listed_identifiers,
        identifier,
        work.id,
        record_id,
    )


async def _semantic_scholar(
    session: AsyncSession,
    sources: Sources,
    paper_id: uuid.UUID,
    manifestation_id: uuid.UUID,
    identifier: Identifier,
) -> None:
    await apply_semantic_scholar(
        session,
        paper_id,
        manifestation_id,
        identifier,
        await sources.semantic_scholar.fetch(identifier),
    )


async def apply_semantic_scholar(
    session: AsyncSession,
    paper_id: uuid.UUID,
    manifestation_id: uuid.UUID,
    identifier: Identifier,
    fetched: FetchedS2Paper,
) -> None:
    """Attach a Semantic Scholar record (lookup or search hit) to a manifestation."""
    paper, record_id, at = fetched.paper, fetched.source_record_id, fetched.fetched_at
    await _link_record(session, paper_id, manifestation_id, record_id)
    await _add_own_identifier(
        session,
        paper_id,
        manifestation_id,
        IdentifierScheme.S2_PAPER,
        paper.paper_id,
        SourceName.SEMANTIC_SCHOLAR,
        record_id,
    )
    if paper.corpus_id:
        await _add_own_identifier(
            session,
            paper_id,
            manifestation_id,
            IdentifierScheme.S2_CORPUS,
            paper.corpus_id,
            SourceName.SEMANTIC_SCHOLAR,
            record_id,
        )
    reported = paper.reported_date()
    if reported:
        value, precision = reported
        await add_date(
            session,
            paper_id,
            manifestation_id,
            DateEvent.REPORTED_PUBLICATION_DATE,
            value,
            precision,
            is_primary=False,
            reporting=ReportingSource.SEMANTIC_SCHOLAR,
            upstream=UpstreamSource.UNKNOWN,
            evidence={"record": paper.paper_id, "field": "publicationDate"},
            record_id=record_id,
            retrieved_at=at,
        )
    listed = tuple(
        i for i in paper.listed_identifiers if i.scheme is not IdentifierScheme.S2_CORPUS
    )
    await _listing_links(
        session,
        paper_id,
        manifestation_id,
        SourceName.SEMANTIC_SCHOLAR,
        listed,
        identifier,
        paper.paper_id,
        record_id,
    )


async def _link_record(
    session: AsyncSession, paper_id: uuid.UUID, manifestation_id: uuid.UUID, record_id: uuid.UUID
) -> None:
    await session.execute(
        sa.text(
            "INSERT INTO paper_source_links (paper_id, source_record_id, manifestation_id) "
            "VALUES (:p, :r, :m) ON CONFLICT DO NOTHING"
        ),
        {"p": paper_id, "r": record_id, "m": manifestation_id},
    )


async def _add_own_identifier(
    session: AsyncSession,
    paper_id: uuid.UUID,
    manifestation_id: uuid.UUID,
    scheme: IdentifierScheme,
    value: str,
    source: SourceName,
    record_id: uuid.UUID,
) -> None:
    """The aggregator's own ID, unless another work already holds it (then the listing link
    below lets the Version Matcher compare the two works instead)."""
    await session.execute(
        sa.text(
            "INSERT INTO paper_identifiers (id, paper_id, manifestation_id, scheme, value, "
            "source, source_record_id) VALUES (gen_random_uuid(), :p, :m, :sc, :v, :s, :r) "
            "ON CONFLICT (scheme, value) DO NOTHING"
        ),
        {
            "p": paper_id,
            "m": manifestation_id,
            "sc": scheme.value,
            "v": value,
            "s": source.value,
            "r": record_id,
        },
    )


async def _listing_links(
    session: AsyncSession,
    paper_id: uuid.UUID,
    manifestation_id: uuid.UUID,
    source: SourceName,
    listed: tuple[Identifier, ...],
    looked_up: Identifier,
    record: str,
    record_id: uuid.UUID,
) -> None:
    links = [
        StatedLink(
            SAME_RECORD, i.scheme, i.value, {"record": record, "looked_up_by": str(looked_up)}
        )
        for i in listed
        if (i.scheme, i.value) != (looked_up.scheme, looked_up.value)
    ]
    await record_links(session, paper_id, manifestation_id, source, links, record_id)
