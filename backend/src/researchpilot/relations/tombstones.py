"""Deletion-marker lifecycle (ARCHITECTURE §12.6a).

Markers are written by database triggers whenever a graph node or relationship is deleted,
moved (merge/split), rejected or retracted. They hold only uid, kind, reason and timestamps.
A marker is purged once the graph confirms the element is absent, and in any case 30 days
after the deletion. Until Neo4j exists (R2) nothing can be verified, so purging at the cap is
expected and not an alert; with a graph backend it raises one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.core.logging import get_logger

log = get_logger(component="tombstones")


@dataclass(frozen=True)
class PurgeReport:
    purged: int
    purged_unverified: int


async def mark_absent(session: AsyncSession, uids: list[uuid.UUID], now: datetime) -> int:
    """Reconciliation confirmed these elements are absent from the graph (R2)."""
    result = await session.execute(
        sa.text(
            "UPDATE entity_tombstones SET verified_absent_at = :now, "
            "graph_removed_at = coalesce(graph_removed_at, :now), "
            "purge_after = least(purge_after, :now) WHERE uid = ANY(:u)"
        ),
        {"u": uids, "now": now},
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def purge(session: AsyncSession, now: datetime, *, graph_enabled: bool) -> PurgeReport:
    rows = (
        (
            await session.execute(
                sa.text(
                    "DELETE FROM entity_tombstones WHERE purge_after <= :now "
                    "RETURNING verified_absent_at IS NULL AS unverified"
                ),
                {"now": now},
            )
        )
        .scalars()
        .all()
    )
    unverified = sum(1 for r in rows if r)
    if unverified and graph_enabled:
        log.error("graph.tombstones_purged_unverified", count=unverified)
    elif rows:
        log.info("graph.tombstones_purged", count=len(rows), unverified=unverified)
    return PurgeReport(purged=len(rows), purged_unverified=unverified)
