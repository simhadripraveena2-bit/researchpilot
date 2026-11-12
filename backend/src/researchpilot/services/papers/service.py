"""Add a paper to a project by identifier, and read a paper with its full date provenance."""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.core.errors import CapabilityUnavailable, NotFound
from researchpilot.domain.enums import DiscoveredVia, SourceName
from researchpilot.domain.identifiers import (
    Identifier,
    IdentifierScheme,
    arxiv_id_from_doi,
    parse_identifier,
)
from researchpilot.integrations.base import SourceError, SourceNotFound
from researchpilot.integrations.biorxiv import is_server_preprint_doi, likely_server
from researchpilot.integrations.registry import Sources
from researchpilot.services.matching.store import match_work
from researchpilot.services.papers.enrich import enrich_work
from researchpilot.services.papers.ingest import ingest_arxiv
from researchpilot.services.papers.ingest_biorxiv import ingest_preprint_server
from researchpilot.services.papers.ingest_crossref import ingest_crossref

log = structlog.get_logger(__name__)


MAX_FOLLOWED_LINKS = 3


async def add_paper_by_identifier(
    session: AsyncSession, sources: Sources, project_id: uuid.UUID, text: str
) -> tuple[uuid.UUID, bool, dict[str, str]]:
    """Returns (paper id, whether it was newly added to the project, enrichment coverage).

    New works: ingest from the identifier's system of record, follow the work's decisive
    version links (fetching the other version), then run the Version Matcher; the project
    membership attaches to the surviving work.
    """
    identifier = parse_identifier(text)
    if identifier.scheme is IdentifierScheme.DOI and (arxiv := arxiv_id_from_doi(identifier.value)):
        identifier = Identifier(IdentifierScheme.ARXIV, arxiv)

    coverage: dict[str, str] = {}
    paper_id = await _known_paper(session, identifier)
    if paper_id is None:
        paper_id = await ingest_identifier(session, sources, identifier)
        await follow_version_links(session, sources, paper_id)
        paper_id = await match_work(session, paper_id)
        coverage = await enrich_work(session, sources, paper_id)
        paper_id = await match_work(session, paper_id)  # strong evidence may now match

    added = (
        await session.execute(
            sa.text(
                # The objective version in use when the item entered the project (kept).
                "INSERT INTO project_items (project_id, item_id, discovered_via, "
                "objective_version) VALUES (:p, :i, :v, (SELECT o.version FROM projects pr "
                "JOIN research_objectives o ON o.id = pr.active_objective_id WHERE pr.id = :p)) "
                "ON CONFLICT DO NOTHING RETURNING item_id"
            ),
            {"p": project_id, "i": paper_id, "v": DiscoveredVia.MANUAL.value},
        )
    ).scalar_one_or_none()
    return paper_id, added is not None, coverage


async def ingest_identifier(
    session: AsyncSession, sources: Sources, identifier: Identifier
) -> uuid.UUID:
    """Fetches the identifier from its system of record and stores it (no matching)."""
    if identifier.scheme is IdentifierScheme.ARXIV:
        return (await ingest_arxiv(session, await sources.arxiv.fetch(identifier))).paper_id
    if identifier.scheme is IdentifierScheme.DOI and is_server_preprint_doi(identifier.value):
        return await _add_server_preprint(session, sources, identifier.value)
    if identifier.scheme is IdentifierScheme.DOI:
        fetched = await sources.crossref.fetch(identifier.value)
        return (await ingest_crossref(session, fetched)).paper_id
    if identifier.scheme in (
        IdentifierScheme.OPENALEX,
        IdentifierScheme.S2_PAPER,
        IdentifierScheme.S2_CORPUS,
    ):
        # Aggregator IDs are resolved to the identifier of a system of record.
        return await ingest_identifier(
            session, sources, await _system_of_record_identifier(sources, identifier)
        )
    raise CapabilityUnavailable(
        f"Adding papers by {identifier.scheme.value} identifier is not available yet; "
        "use a DOI or an arXiv ID",
        scheme=identifier.scheme.value,
    )


async def _system_of_record_identifier(sources: Sources, identifier: Identifier) -> Identifier:
    if identifier.scheme is IdentifierScheme.OPENALEX:
        listed = (await sources.openalex.fetch(identifier)).work.listed_identifiers
    else:
        listed = (await sources.semantic_scholar.fetch(identifier)).paper.listed_identifiers
    for scheme in (IdentifierScheme.DOI, IdentifierScheme.ARXIV):
        for found in listed:
            if found.scheme is scheme:
                return found
    raise CapabilityUnavailable(
        f"{identifier} lists no DOI or arXiv ID, so its system of record is unknown",
        scheme=identifier.scheme.value,
    )


async def follow_version_links(
    session: AsyncSession, sources: Sources, paper_id: uuid.UUID
) -> list[uuid.UUID]:
    """Fetches the targets of the work's decisive version links that are not stored yet
    (one level, at most ``MAX_FOLLOWED_LINKS``). A failed lookup only reduces coverage."""
    targets = (
        await session.execute(
            sa.text(
                "SELECT DISTINCT l.target_scheme, l.target_value FROM paper_version_links l "
                "WHERE l.paper_id = :p AND l.strength = 'decisive' AND NOT EXISTS ("
                "SELECT 1 FROM paper_identifiers i WHERE i.scheme = l.target_scheme "
                "AND i.value = l.target_value) ORDER BY 1, 2 LIMIT :n"
            ),
            {"p": paper_id, "n": MAX_FOLLOWED_LINKS},
        )
    ).all()
    fetched: list[uuid.UUID] = []
    for scheme, value in targets:
        identifier = Identifier(IdentifierScheme(scheme), value)
        try:
            async with session.begin_nested():
                fetched.append(await ingest_identifier(session, sources, identifier))
        except (SourceError, CapabilityUnavailable) as exc:
            log.warning(
                "papers.version_link_not_followed",
                target=str(identifier),
                reason=type(exc).__name__,
            )
    return fetched


async def _add_server_preprint(session: AsyncSession, sources: Sources, doi: str) -> uuid.UUID:
    """bioRxiv or medRxiv (the likely server first, then the other). If neither server has
    the DOI or the API is unavailable, Crossref is used; the posting date then stays
    unconfirmed (Crossref is not the system of record for these preprints)."""
    first = sources.medrxiv if likely_server(doi) is SourceName.MEDRXIV_API else sources.biorxiv
    second = sources.biorxiv if first is sources.medrxiv else sources.medrxiv
    for server in (first, second):
        try:
            fetched = await server.fetch(doi)
        except SourceNotFound:
            continue
        except SourceError as exc:
            log.warning("papers.preprint_server_unavailable", source=exc.source.value, doi=doi)
            break
        return (await ingest_preprint_server(session, fetched)).paper_id
    return (await ingest_crossref(session, await sources.crossref.fetch(doi))).paper_id


async def _known_paper(session: AsyncSession, identifier: Identifier) -> uuid.UUID | None:
    found = (
        await session.execute(
            sa.text("SELECT paper_id FROM paper_identifiers WHERE scheme = :s AND value = :v"),
            {"s": identifier.scheme.value, "v": identifier.value},
        )
    ).scalar_one_or_none()
    return uuid.UUID(str(found)) if found is not None else None


async def list_project_papers(session: AsyncSession, project_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                sa.text(
                    "SELECT p.id, p.title, p.year, p.date_confidence, p.first_public_appearance, "
                    "p.first_public_basis, p.candidate_public_date, pi.inclusion, "
                    "pi.reading_status, pi.discovered_via, pi.first_seen_at FROM project_items pi "
                    "JOIN papers p ON p.id = pi.item_id WHERE pi.project_id = :p "
                    "ORDER BY pi.first_seen_at DESC"
                ),
                {"p": project_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def get_project_paper(
    session: AsyncSession, project_id: uuid.UUID, paper_id: uuid.UUID
) -> dict[str, Any]:
    paper = (
        (
            await session.execute(
                sa.text(
                    "SELECT p.*, pi.inclusion, pi.reading_status, pi.discovered_via, pi.is_saved "
                    "FROM papers p JOIN project_items pi ON pi.item_id = p.id "
                    "WHERE p.id = :id AND pi.project_id = :proj"
                ),
                {"id": paper_id, "proj": project_id},
            )
        )
        .mappings()
        .first()
    )
    if paper is None:
        raise NotFound("paper not found in this project")
    manifestations = (
        (
            await session.execute(
                sa.text(
                    "SELECT id, kind, server_or_venue, primary_identifier_scheme, "
                    "primary_identifier_value, peer_review_label, url, is_open_access "
                    "FROM paper_manifestations WHERE paper_id = :p ORDER BY created_at"
                ),
                {"p": paper_id},
            )
        )
        .mappings()
        .all()
    )
    identifiers = (
        (
            await session.execute(
                sa.text(
                    "SELECT manifestation_id, scheme, value, version, source "
                    "FROM paper_identifiers WHERE paper_id = :p ORDER BY scheme, value"
                ),
                {"p": paper_id},
            )
        )
        .mappings()
        .all()
    )
    dates = (
        (
            await session.execute(
                sa.text(
                    "SELECT id, manifestation_id, event, value, precision, version, is_primary, "
                    "reporting_source, upstream_source, upstream_evidence, source_record_id, "
                    "retrieved_at, flags FROM paper_dates WHERE paper_id = :p ORDER BY value, event"
                ),
                {"p": paper_id},
            )
        )
        .mappings()
        .all()
    )
    authors = (
        (
            await session.execute(
                sa.text(
                    "SELECT manifestation_id, position, raw_name FROM paper_authors "
                    "WHERE paper_id = :p ORDER BY manifestation_id, position"
                ),
                {"p": paper_id},
            )
        )
        .mappings()
        .all()
    )
    return {
        "paper": dict(paper),
        "manifestations": [dict(m) for m in manifestations],
        "identifiers": [dict(i) for i in identifiers],
        "dates": [dict(d) for d in dates],
        "authors": [dict(a) for a in authors],
    }
