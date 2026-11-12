"""Release types for a project's papers in a date window (read-only; computed on demand).

Loads each work's stored date events and manifestations and runs the pure classifier.
Nothing is written: release types are derived from the stored events, so they change only
when events or matches change. (Snapshots for "Reclassified" badges belong to Latest
Research scans, M1c.)
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.domain.enums import (
    ManifestationKind,
    PeerReviewLabel,
    PublicationType,
)
from researchpilot.domain.windows import Window
from researchpilot.services.dates.release_types import (
    ManifestationInfo,
    Release,
    WorkDates,
    classify,
)
from researchpilot.services.dates.store import load_claims


async def load_work_dates(session: AsyncSession, paper_id: uuid.UUID) -> WorkDates:
    manifestations = {
        r.id: ManifestationInfo(
            id=r.id,
            kind=ManifestationKind(r.kind),
            publication_type=PublicationType(r.publication_type),
            server_or_venue=r.server_or_venue,
            peer_review_label=PeerReviewLabel(r.peer_review_label),
        )
        for r in await session.execute(
            sa.text(
                "SELECT id, kind, publication_type, server_or_venue, peer_review_label "
                "FROM paper_manifestations WHERE paper_id = :p"
            ),
            {"p": paper_id},
        )
    }
    checked = frozenset(
        r.source
        for r in await session.execute(
            sa.text(
                "SELECT DISTINCT r.source FROM paper_source_links l "
                "JOIN source_records r ON r.id = l.source_record_id WHERE l.paper_id = :p"
            ),
            {"p": paper_id},
        )
    )
    claims = tuple(await load_claims(session, paper_id))
    return WorkDates(paper_id, claims, manifestations, checked)


async def project_releases(
    session: AsyncSession, project_id: uuid.UUID, window: Window, as_of: datetime
) -> list[tuple[uuid.UUID, str, Release]]:
    """(paper id, title, release) for every project paper with something in the window."""
    papers = (
        await session.execute(
            sa.text(
                "SELECT p.id, p.title FROM project_items pi JOIN papers p ON p.id = pi.item_id "
                "WHERE pi.project_id = :proj AND p.merged_into_id IS NULL ORDER BY p.id"
            ),
            {"proj": project_id},
        )
    ).all()
    out: list[tuple[uuid.UUID, str, Release]] = []
    for paper in papers:
        release = classify(await load_work_dates(session, paper.id), window, as_of)
        if release is not None:
            out.append((paper.id, paper.title, release))
    out.sort(key=lambda item: item[2].event.value, reverse=True)
    return out


def counts(releases: list[tuple[uuid.UUID, str, Release]]) -> dict[str, int]:
    tally: dict[str, int] = defaultdict(int)
    for _, _, release in releases:
        tally[release.release_type.value] += 1
    return dict(tally)
