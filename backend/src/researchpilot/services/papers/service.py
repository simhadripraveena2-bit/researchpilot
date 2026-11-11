"""Add a paper to a project by identifier, and read a paper with its full date provenance."""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.core.errors import CapabilityUnavailable, NotFound
from researchpilot.domain.enums import DiscoveredVia
from researchpilot.domain.identifiers import (
    Identifier,
    IdentifierScheme,
    arxiv_id_from_doi,
    parse_identifier,
)
from researchpilot.integrations.registry import Sources
from researchpilot.services.papers.ingest import ingest_arxiv
from researchpilot.services.papers.ingest_crossref import ingest_crossref


async def add_paper_by_identifier(
    session: AsyncSession, sources: Sources, project_id: uuid.UUID, text: str
) -> tuple[uuid.UUID, bool]:
    """Returns (paper id, whether it was newly added to the project)."""
    identifier = parse_identifier(text)
    if identifier.scheme is IdentifierScheme.DOI and (arxiv := arxiv_id_from_doi(identifier.value)):
        identifier = Identifier(IdentifierScheme.ARXIV, arxiv)

    paper_id = await _known_paper(session, identifier)
    if paper_id is None:
        if identifier.scheme is IdentifierScheme.ARXIV:
            paper_id = (await ingest_arxiv(session, await sources.arxiv.fetch(identifier))).paper_id
        elif identifier.scheme is IdentifierScheme.DOI:
            fetched = await sources.crossref.fetch(identifier.value)
            paper_id = (await ingest_crossref(session, fetched)).paper_id
        else:
            raise CapabilityUnavailable(
                f"Adding papers by {identifier.scheme.value} identifier is not available yet; "
                "use a DOI or an arXiv ID",
                scheme=identifier.scheme.value,
            )

    added = (
        await session.execute(
            sa.text(
                "INSERT INTO project_items (project_id, item_id, discovered_via) "
                "VALUES (:p, :i, :v) ON CONFLICT DO NOTHING RETURNING item_id"
            ),
            {"p": project_id, "i": paper_id, "v": DiscoveredVia.MANUAL.value},
        )
    ).scalar_one_or_none()
    return paper_id, added is not None


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
