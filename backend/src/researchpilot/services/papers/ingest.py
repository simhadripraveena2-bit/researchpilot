"""Turn source records into works, manifestations, identifiers and date events.

Ingestion is idempotent: the identifier (``paper_identifiers`` UNIQUE(scheme, value)) finds
an existing manifestation, and date events are inserted once per distinct claim
(``uq_paper_dates_claim``). Existing events are never changed; the Date Resolver runs after
every ingestion and recomputes the work's resolved dates from all its events.
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.core.ids import uuid7
from researchpilot.domain.enums import (
    DateEvent,
    DatePrecision,
    ManifestationKind,
    PeerReviewLabel,
    PublicationType,
    ReportingSource,
    SourceName,
    UpstreamSource,
)
from researchpilot.domain.identifiers import IdentifierScheme
from researchpilot.integrations.arxiv import FetchedEntry
from researchpilot.services.dates.store import resolve_paper_dates
from researchpilot.services.matching.links import StatedLink, record_links, target


@dataclass(frozen=True)
class IngestResult:
    paper_id: uuid.UUID
    manifestation_id: uuid.UUID
    created: bool


def normalize_title(title: str) -> str:
    """Lower case, accents removed, punctuation to spaces, whitespace collapsed."""
    text = unicodedata.normalize("NFKD", title)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


async def ingest_arxiv(session: AsyncSession, fetched: FetchedEntry) -> IngestResult:
    entry, record_id, retrieved_at = fetched.entry, fetched.source_record_id, fetched.fetched_at
    existing = (
        await session.execute(
            sa.text(
                "SELECT paper_id, manifestation_id FROM paper_identifiers "
                "WHERE scheme = 'arxiv' AND value = :v"
            ),
            {"v": entry.arxiv_id},
        )
    ).first()
    created = existing is None
    if existing is None:
        paper_id = await create_work(session, entry.title, entry.abstract, record_id)
        manifestation_id = await create_manifestation(
            session,
            paper_id,
            kind=ManifestationKind.PREPRINT,
            server="arxiv",
            scheme=IdentifierScheme.ARXIV,
            value=entry.arxiv_id,
            label=PeerReviewLabel.PREPRINT_NOT_PEER_REVIEWED,  # moderated, not peer-reviewed
            publication_type=PublicationType.PREPRINT,
            url=entry.abs_url,
            is_open_access=True,
            record_id=record_id,
        )
        await session.execute(
            sa.text(
                "UPDATE papers SET abstract_manifestation_id = :m, year = :y, "
                "fields_of_study = :f, field_sources = CAST(:fs AS jsonb) WHERE id = :p"
            ),
            {
                "m": manifestation_id,
                "y": entry.submitted_v1.year,
                "f": list(entry.categories),
                "fs": json.dumps(
                    {"title": "arxiv_api", "abstract": "arxiv_api", "fields_of_study": "arxiv_api"}
                ),
                "p": paper_id,
            },
        )
        await add_identifier(
            session,
            paper_id,
            manifestation_id,
            IdentifierScheme.ARXIV,
            entry.arxiv_id,
            entry.latest_version,
            SourceName.ARXIV_API,
            record_id,
        )
        await add_date(
            session,
            paper_id,
            manifestation_id,
            DateEvent.FIRST_SEEN_BY_RESEARCHPILOT,
            retrieved_at,
            DatePrecision.TIMESTAMP,
            is_primary=False,
            reporting=ReportingSource.RESEARCHPILOT,
            upstream=UpstreamSource.UNKNOWN,
            evidence=None,
            record_id=None,
            retrieved_at=retrieved_at,
        )
    else:
        paper_id, manifestation_id = existing.paper_id, existing.manifestation_id
        await session.execute(
            sa.text(
                "UPDATE paper_identifiers SET version = greatest(coalesce(version, 0), :v) "
                "WHERE scheme = 'arxiv' AND value = :id"
            ),
            {"v": entry.latest_version, "id": entry.arxiv_id},
        )

    await session.execute(
        sa.text(
            "INSERT INTO paper_source_links (paper_id, source_record_id, manifestation_id) "
            "VALUES (:p, :r, :m) ON CONFLICT DO NOTHING"
        ),
        {"p": paper_id, "r": record_id, "m": manifestation_id},
    )
    await replace_authors(
        session, paper_id, manifestation_id, [(a.name, list(a.affiliations)) for a in entry.authors]
    )

    # Date events. arXiv is the system of record for its IDs, so these are primary.
    await add_date(
        session,
        paper_id,
        manifestation_id,
        DateEvent.PREPRINT_SUBMITTED,
        entry.submitted_v1,
        DatePrecision.TIMESTAMP,
        version=1,
        is_primary=True,
        reporting=ReportingSource.ARXIV_API,
        upstream=UpstreamSource.ARXIV,
        evidence={"field": "atom:entry/published", "meaning": "v1 submission"},
        record_id=record_id,
        retrieved_at=retrieved_at,
    )
    await add_version(session, paper_id, manifestation_id, 1, entry.submitted_v1, record_id)
    if entry.latest_version > 1:
        await add_date(
            session,
            paper_id,
            manifestation_id,
            DateEvent.VERSION_SUBMITTED,
            entry.submitted_latest,
            DatePrecision.TIMESTAMP,
            version=entry.latest_version,
            is_primary=True,
            reporting=ReportingSource.ARXIV_API,
            upstream=UpstreamSource.ARXIV,
            evidence={
                "field": "atom:entry/updated",
                "meaning": f"v{entry.latest_version} submission",
            },
            record_id=record_id,
            retrieved_at=retrieved_at,
        )
        await add_version(
            session,
            paper_id,
            manifestation_id,
            entry.latest_version,
            entry.submitted_latest,
            record_id,
        )

    if entry.doi and (link := target("doi", entry.doi)):
        await record_links(
            session,
            paper_id,
            manifestation_id,
            SourceName.ARXIV_API,
            [
                StatedLink(
                    "is-preprint-of",
                    link[0],
                    link[1],
                    {"field": "arxiv:doi", "journal_ref": entry.journal_ref},
                )
            ],
            record_id,
        )
    await resolve_paper_dates(session, paper_id, retrieved_at)
    # Announcements captured before this paper entered the record.
    from researchpilot.services.dates.announcements import apply_announcements

    await apply_announcements(session, [entry.arxiv_id])
    return IngestResult(paper_id, manifestation_id, created)


async def create_work(
    session: AsyncSession, title: str, abstract: str | None, record_id: uuid.UUID
) -> uuid.UUID:
    paper_id = uuid7()
    await session.execute(
        sa.text("INSERT INTO research_items (id, item_type) VALUES (:id, 'paper')"),
        {"id": paper_id},
    )
    await session.execute(
        sa.text(
            "INSERT INTO papers (id, title, normalized_title, abstract, abstract_status) "
            "VALUES (:id, :t, :nt, :a, :s)"
        ),
        {
            "id": paper_id,
            "t": title,
            "nt": normalize_title(title),
            "a": abstract or None,
            "s": "available" if abstract else "unavailable",
        },
    )
    return paper_id


async def create_manifestation(
    session: AsyncSession,
    paper_id: uuid.UUID,
    *,
    kind: ManifestationKind,
    server: str,
    scheme: IdentifierScheme,
    value: str,
    label: PeerReviewLabel,
    url: str | None,
    is_open_access: bool | None,
    record_id: uuid.UUID,
    publication_type: PublicationType = PublicationType.OTHER,
) -> uuid.UUID:
    manifestation_id = uuid7()
    await session.execute(
        sa.text(
            "INSERT INTO paper_manifestations (id, paper_id, kind, server_or_venue, "
            "primary_identifier_scheme, primary_identifier_value, peer_review_label, url, "
            "is_open_access, created_from_source_record_id, publication_type) "
            "VALUES (:id, :p, :k, :sv, :sc, :v, :l, :u, :oa, :r, :pt)"
        ),
        {
            "id": manifestation_id,
            "p": paper_id,
            "k": kind.value,
            "sv": server,
            "sc": scheme.value,
            "v": value,
            "l": label.value,
            "u": url,
            "oa": is_open_access,
            "r": record_id,
            "pt": publication_type.value,
        },
    )
    return manifestation_id


async def add_identifier(
    session: AsyncSession,
    paper_id: uuid.UUID,
    manifestation_id: uuid.UUID,
    scheme: IdentifierScheme,
    value: str,
    version: int | None,
    source: SourceName,
    record_id: uuid.UUID,
) -> None:
    await session.execute(
        sa.text(
            "INSERT INTO paper_identifiers (id, paper_id, manifestation_id, scheme, value, "
            "version, source, source_record_id) VALUES (:id, :p, :m, :sc, :v, :ver, :s, :r)"
        ),
        {
            "id": uuid7(),
            "p": paper_id,
            "m": manifestation_id,
            "sc": scheme.value,
            "v": value,
            "ver": version,
            "s": source.value,
            "r": record_id,
        },
    )


async def add_date(
    session: AsyncSession,
    paper_id: uuid.UUID,
    manifestation_id: uuid.UUID,
    event: DateEvent,
    value: datetime,
    precision: DatePrecision,
    *,
    is_primary: bool,
    reporting: ReportingSource,
    upstream: UpstreamSource,
    evidence: dict[str, Any] | None,
    record_id: uuid.UUID | None,
    retrieved_at: datetime,
    version: int | None = None,
) -> None:
    """Insert one date claim unless the same claim is already stored (never overwritten)."""
    await session.execute(
        sa.text(
            "INSERT INTO paper_dates (id, paper_id, manifestation_id, event, value, precision, "
            "version, is_primary, reporting_source, upstream_source, upstream_evidence, "
            "source_record_id, retrieved_at) "
            "VALUES (:id, :p, :m, :e, :v, :pr, :ver, :prim, :rs, :us, CAST(:ev AS jsonb), :r, "
            ":ra) ON CONFLICT (manifestation_id, event, (coalesce(version, 0)), "
            "reporting_source, value, precision) DO NOTHING"
        ),
        {
            "id": uuid7(),
            "p": paper_id,
            "m": manifestation_id,
            "e": event.value,
            "v": value,
            "pr": precision.value,
            "ver": version,
            "prim": is_primary,
            "rs": reporting.value,
            "us": upstream.value,
            "ev": json.dumps(evidence) if evidence else None,
            "r": record_id,
            "ra": retrieved_at,
        },
    )


async def add_version(
    session: AsyncSession,
    paper_id: uuid.UUID,
    manifestation_id: uuid.UUID,
    version: int,
    submitted_at: datetime,
    record_id: uuid.UUID,
    source: SourceName = SourceName.ARXIV_API,
) -> None:
    await session.execute(
        sa.text(
            "INSERT INTO paper_versions (manifestation_id, version, paper_id, submitted_at, "
            "source, source_record_id) VALUES (:m, :v, :p, :s, :src, :r) "
            "ON CONFLICT (manifestation_id, version) DO NOTHING"
        ),
        {
            "m": manifestation_id,
            "v": version,
            "p": paper_id,
            "s": submitted_at,
            "src": source.value,
            "r": record_id,
        },
    )


async def replace_authors(
    session: AsyncSession,
    paper_id: uuid.UUID,
    manifestation_id: uuid.UUID,
    authors: list[tuple[str, list[str]]],
) -> None:
    """The manifestation's author list as its source currently reports it."""
    await session.execute(
        sa.text("DELETE FROM manifestation_authors WHERE manifestation_id = :m"),
        {"m": manifestation_id},
    )
    for position, (name, affiliations) in enumerate(authors, start=1):
        await session.execute(
            sa.text(
                "INSERT INTO manifestation_authors (manifestation_id, position, paper_id, "
                "raw_name, raw_affiliations) VALUES (:m, :pos, :p, :n, CAST(:a AS jsonb))"
            ),
            {
                "m": manifestation_id,
                "pos": position,
                "p": paper_id,
                "n": name,
                "a": json.dumps(affiliations),
            },
        )
