"""Crossref records -> manifestations, identifiers and date events.

Crossref is the system of record for the DOIs it registers (dates "as deposited by the
publisher"), so journal and proceedings dates are primary. bioRxiv/medRxiv preprints are
also registered in Crossref (``posted-content``), but their system of record is the preprint
server's own API: there the Crossref dates are secondary, and their upstream source is the
server named in the record's ``institution`` (exposed by Crossref, so not guessed).

Version links (``relation``) are kept in the source record for the Version Matcher; a
Crossref record never merges works by itself.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

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
from researchpilot.integrations.crossref import CrossrefWork, FetchedWork
from researchpilot.services.dates.store import resolve_paper_dates
from researchpilot.services.matching.links import StatedLink, record_links, target
from researchpilot.services.papers.ingest import (
    IngestResult,
    add_date,
    add_identifier,
    create_manifestation,
    create_work,
    replace_authors,
)

PREPRINT_SERVERS = {"biorxiv": UpstreamSource.BIORXIV, "medrxiv": UpstreamSource.MEDRXIV}
PUBLISHED_TYPES = {"journal-article", "proceedings-article"}

# Crossref field -> date event. "accepted" is mapped only for non-preprints (see module doc
# of integrations.crossref); "posted" only for preprints.
FIELD_EVENTS: dict[str, DateEvent] = {
    "posted": DateEvent.PREPRINT_POSTED,
    "published-online": DateEvent.PUBLISHED_ONLINE,
    "published-print": DateEvent.ISSUE_PUBLISHED,
    "issued": DateEvent.ISSUED,
    "accepted": DateEvent.ACCEPTED,
    "created": DateEvent.INDEX_CREATED,
    "deposited": DateEvent.METADATA_DEPOSITED,
    "indexed": DateEvent.METADATA_INDEXED,
}


# Crossref ``type`` -> publication type (notices are detected from ``update-to`` instead).
CROSSREF_TYPES = {
    "journal-article": PublicationType.JOURNAL_ARTICLE,
    "proceedings-article": PublicationType.CONFERENCE_PAPER,
    "posted-content": PublicationType.PREPRINT,
    "book-chapter": PublicationType.BOOK_CHAPTER,
    "book": PublicationType.BOOK,
    "monograph": PublicationType.BOOK,
    "dissertation": PublicationType.DISSERTATION,
    "report": PublicationType.REPORT,
    "dataset": PublicationType.DATASET,
}
NOTICE_KINDS = {
    "correction": PublicationType.CORRECTION,
    "erratum": PublicationType.CORRECTION,
    "corrigendum": PublicationType.CORRECTION,
    "retraction": PublicationType.RETRACTION,
    "withdrawal": PublicationType.RETRACTION,
    "removal": PublicationType.RETRACTION,
    "expression_of_concern": PublicationType.EXPRESSION_OF_CONCERN,
}
# Links between a notice and the work it is about (Version Matcher: related, not same).
NOTICE_LINKS = {
    PublicationType.CORRECTION: ("is-correction-of", "has-correction"),
    PublicationType.RETRACTION: ("is-retraction-of", "has-retraction"),
    PublicationType.EXPRESSION_OF_CONCERN: (
        "is-expression-of-concern-for",
        "has-expression-of-concern",
    ),
}


def publication_type(work: CrossrefWork) -> PublicationType:
    for update in work.updates:
        if update.type in NOTICE_KINDS:
            return NOTICE_KINDS[update.type]
    if work.is_preprint:
        return PublicationType.PREPRINT
    return CROSSREF_TYPES.get(work.type, PublicationType.OTHER)


def classify(work: CrossrefWork) -> tuple[ManifestationKind, str, PeerReviewLabel]:
    if work.is_preprint:
        server = (work.institution or work.publisher or "preprint server").strip()
        key = server.lower()
        return (
            ManifestationKind.PREPRINT,
            key if key in PREPRINT_SERVERS else server,
            PeerReviewLabel.PREPRINT_NOT_PEER_REVIEWED,
        )
    venue = work.container_title or work.publisher or "unknown venue"
    if work.type in PUBLISHED_TYPES:
        return ManifestationKind.PUBLISHED, venue, PeerReviewLabel.JOURNAL_VERSION
    return ManifestationKind.OTHER, venue, PeerReviewLabel.UNKNOWN


def notice_links(work: CrossrefWork) -> list[tuple[str, str, dict[str, object]]]:
    """(link type, target DOI, evidence) for update-to and updated-by entries."""
    out: list[tuple[str, str, dict[str, object]]] = []
    for field, entries, side in (
        ("update-to", work.updates, 0),
        ("updated-by", work.updated_by, 1),
    ):
        for u in entries:
            kind = NOTICE_KINDS.get(u.type)
            if kind is None:
                continue
            out.append(
                (
                    NOTICE_LINKS[kind][side],
                    u.doi,
                    {"field": field, "type": u.type, "source": u.source},
                )
            )
    return out


async def ingest_crossref(session: AsyncSession, fetched: FetchedWork) -> IngestResult:
    work, record_id, retrieved_at = fetched.work, fetched.source_record_id, fetched.fetched_at
    kind, server, label = classify(work)
    existing = (
        await session.execute(
            sa.text(
                "SELECT paper_id, manifestation_id FROM paper_identifiers "
                "WHERE scheme = 'doi' AND value = :v"
            ),
            {"v": work.doi},
        )
    ).first()
    created = existing is None
    if existing is None:
        paper_id = await create_work(session, work.title, work.abstract, record_id)
        manifestation_id = await create_manifestation(
            session,
            paper_id,
            kind=kind,
            server=server,
            scheme=IdentifierScheme.DOI,
            value=work.doi,
            label=label,
            publication_type=publication_type(work),
            url=work.url,
            is_open_access=None,
            record_id=record_id,
        )
        published = work.dates.get("published-online") or work.dates.get("issued")
        await session.execute(
            sa.text(
                "UPDATE papers SET abstract_manifestation_id = CASE WHEN :a THEN :m END, "
                "year = :y, venue = :venue, publication_type = :t, "
                "field_sources = CAST(:fs AS jsonb) WHERE id = :p"
            ),
            {
                "a": work.abstract is not None,
                "m": manifestation_id,
                "y": published.value.year if published else None,
                "venue": None if kind is ManifestationKind.PREPRINT else server,
                "t": work.type,
                "fs": json.dumps({"title": "crossref", "venue": "crossref"}),
                "p": paper_id,
            },
        )
        await add_identifier(
            session,
            paper_id,
            manifestation_id,
            IdentifierScheme.DOI,
            work.doi,
            None,
            SourceName.CROSSREF,
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
            "INSERT INTO paper_source_links (paper_id, source_record_id, manifestation_id) "
            "VALUES (:p, :r, :m) ON CONFLICT DO NOTHING"
        ),
        {"p": paper_id, "r": record_id, "m": manifestation_id},
    )
    await replace_authors(
        session, paper_id, manifestation_id, [(a.name, list(a.affiliations)) for a in work.authors]
    )
    await add_crossref_dates(session, paper_id, manifestation_id, work, record_id, retrieved_at)
    stated = [
        StatedLink(
            rel.type,
            *found,
            {"field": f"relation.{rel.type}", "id": rel.id, "asserted_by": rel.asserted_by},
        )
        for rel in work.relations
        if (found := target(rel.id_type, rel.id)) is not None
        and found != (IdentifierScheme.DOI, work.doi)
    ]
    stated += [
        StatedLink(link_type, IdentifierScheme.DOI, doi, evidence)
        for link_type, doi, evidence in notice_links(work)
    ]
    await record_links(session, paper_id, manifestation_id, SourceName.CROSSREF, stated, record_id)
    await resolve_paper_dates(session, paper_id, retrieved_at)
    return IngestResult(paper_id, manifestation_id, created)


async def add_crossref_dates(
    session: AsyncSession,
    paper_id: uuid.UUID,
    manifestation_id: uuid.UUID,
    work: CrossrefWork,
    record_id: uuid.UUID,
    retrieved_at: datetime,
) -> None:
    server_upstream = PREPRINT_SERVERS.get((work.institution or "").lower())
    # bioRxiv/medRxiv preprints: the server API is the system of record (secondary here).
    is_primary = not (work.is_preprint and server_upstream is not None)
    upstream = (
        server_upstream if (work.is_preprint and server_upstream) else UpstreamSource.CROSSREF
    )
    for field, date in work.dates.items():
        event = FIELD_EVENTS[field]
        if field == "posted" and not work.is_preprint:
            continue
        if field == "accepted" and work.is_preprint:
            continue  # tracks the latest preprint version, not a journal acceptance
        evidence: dict[str, object] = {"field": field, "date_parts": list(date.parts)}
        if field == "issued":
            evidence["meaning"] = "Crossref-derived earliest publication date"
        if upstream is not UpstreamSource.CROSSREF:
            evidence["upstream_field"] = "institution[0].name"
        await add_date(
            session,
            paper_id,
            manifestation_id,
            event,
            date.value,
            date.precision,
            is_primary=is_primary and event not in _METADATA_EVENTS,
            reporting=ReportingSource.CROSSREF,
            upstream=upstream,
            evidence=evidence,
            record_id=record_id,
            retrieved_at=retrieved_at,
        )


_METADATA_EVENTS = {DateEvent.METADATA_DEPOSITED, DateEvent.METADATA_INDEXED}
