"""bioRxiv/medRxiv records -> preprint manifestation, versions and posting events.

The server is the system of record for its preprints, so posting dates are primary:
v1 -> ``preprint_posted`` (a public-availability event), v2+ -> ``version_posted`` (never the
work's first appearance). If Crossref already created the manifestation (same DOI), the
server's events are added to it; nothing is overwritten.
"""

from __future__ import annotations

import json

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
from researchpilot.integrations.biorxiv import SERVER_NAME, FetchedPreprint, posted_at
from researchpilot.services.dates.store import resolve_paper_dates
from researchpilot.services.matching.links import StatedLink, record_links, target
from researchpilot.services.papers.ingest import (
    IngestResult,
    add_date,
    add_identifier,
    add_version,
    create_manifestation,
    create_work,
    replace_authors,
)

REPORTING = {
    SourceName.BIORXIV_API: (ReportingSource.BIORXIV_API, UpstreamSource.BIORXIV),
    SourceName.MEDRXIV_API: (ReportingSource.MEDRXIV_API, UpstreamSource.MEDRXIV),
}


async def ingest_preprint_server(session: AsyncSession, fetched: FetchedPreprint) -> IngestResult:
    preprint, record_id, retrieved_at = (
        fetched.preprint,
        fetched.source_record_id,
        fetched.fetched_at,
    )
    latest = preprint.latest
    server = SERVER_NAME[preprint.server]
    reporting, upstream = REPORTING[preprint.server]
    existing = (
        await session.execute(
            sa.text(
                "SELECT paper_id, manifestation_id FROM paper_identifiers "
                "WHERE scheme = 'doi' AND value = :v"
            ),
            {"v": preprint.doi},
        )
    ).first()
    created = existing is None
    if existing is None:
        paper_id = await create_work(session, latest.title, latest.abstract, record_id)
        manifestation_id = await create_manifestation(
            session,
            paper_id,
            kind=ManifestationKind.PREPRINT,
            server=server,
            scheme=IdentifierScheme.DOI,
            value=preprint.doi,
            label=PeerReviewLabel.PREPRINT_NOT_PEER_REVIEWED,
            publication_type=PublicationType.PREPRINT,
            url=f"https://www.{server}.org/content/{preprint.doi}v{latest.version}",
            is_open_access=True,
            record_id=record_id,
        )
        await session.execute(
            sa.text(
                "UPDATE papers SET abstract_manifestation_id = CASE WHEN :a THEN :m END, "
                "year = :y, fields_of_study = :f, field_sources = CAST(:fs AS jsonb) "
                "WHERE id = :p"
            ),
            {
                "a": latest.abstract is not None,
                "m": manifestation_id,
                "y": preprint.versions[0].posted.year,
                "f": [latest.category] if latest.category else [],
                "fs": json.dumps({"title": reporting.value, "abstract": reporting.value}),
                "p": paper_id,
            },
        )
        await add_identifier(
            session,
            paper_id,
            manifestation_id,
            IdentifierScheme.DOI,
            preprint.doi,
            latest.version,
            preprint.server,
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
                "WHERE scheme = 'doi' AND value = :d"
            ),
            {"v": latest.version, "d": preprint.doi},
        )

    await session.execute(
        sa.text(
            "INSERT INTO paper_source_links (paper_id, source_record_id, manifestation_id) "
            "VALUES (:p, :r, :m) ON CONFLICT DO NOTHING"
        ),
        {"p": paper_id, "r": record_id, "m": manifestation_id},
    )
    await replace_authors(
        session, paper_id, manifestation_id, [(name, []) for name in latest.authors]
    )
    for v in preprint.versions:
        event = DateEvent.PREPRINT_POSTED if v.version == 1 else DateEvent.VERSION_POSTED
        await add_date(
            session,
            paper_id,
            manifestation_id,
            event,
            posted_at(v.posted),
            DatePrecision.DAY,
            version=v.version,
            is_primary=True,
            reporting=reporting,
            upstream=upstream,
            evidence={
                "field": f"collection[version={v.version}].date",
                "meaning": f"v{v.version} posting date",
            },
            record_id=record_id,
            retrieved_at=retrieved_at,
        )
        await add_version(
            session,
            paper_id,
            manifestation_id,
            v.version,
            posted_at(v.posted),
            record_id,
            source=preprint.server,
        )
    if preprint.published_doi and (link := target("doi", preprint.published_doi)):
        await record_links(
            session,
            paper_id,
            manifestation_id,
            preprint.server,
            [StatedLink("is-preprint-of", link[0], link[1], {"field": "collection[].published"})],
            record_id,
        )
    await resolve_paper_dates(session, paper_id, retrieved_at)
    return IngestResult(paper_id, manifestation_id, created)
