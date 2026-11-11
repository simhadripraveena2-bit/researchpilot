"""Load a work's date events, run the Date Resolver and store the result on ``papers``."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.domain.enums import (
    DateEvent,
    DatePrecision,
    ReportingSource,
    UpstreamSource,
)
from researchpilot.services.dates.resolver import DateClaim, DateResolution, resolve

RESOLVER_FLAGS = ("future_date", "disagrees_with_primary")


async def load_claims(session: AsyncSession, paper_id: uuid.UUID) -> list[DateClaim]:
    rows = (
        await session.execute(
            sa.text(
                "SELECT id, manifestation_id, event, value, precision, is_primary, "
                "reporting_source, upstream_source, version FROM paper_dates "
                "WHERE paper_id = :p"
            ),
            {"p": paper_id},
        )
    ).all()
    return [
        DateClaim(
            id=r.id,
            manifestation_id=r.manifestation_id,
            event=DateEvent(r.event),
            value=r.value,
            precision=DatePrecision(r.precision),
            is_primary=r.is_primary,
            reporting_source=ReportingSource(r.reporting_source),
            upstream_source=UpstreamSource(r.upstream_source),
            version=r.version,
        )
        for r in rows
    ]


async def resolve_paper_dates(
    session: AsyncSession, paper_id: uuid.UUID, retrieved_at: datetime
) -> DateResolution:
    result = resolve(await load_claims(session, paper_id), retrieved_at)
    # Resolver flags are recomputed; other flags (e.g. boundary_day) are left alone.
    await session.execute(
        sa.text(
            "UPDATE paper_dates SET flags = ARRAY(SELECT f FROM unnest(flags) f "
            "WHERE f <> ALL(CAST(:resolver AS text[]))) WHERE paper_id = :p"
        ),
        {"p": paper_id, "resolver": list(RESOLVER_FLAGS)},
    )
    for claim_id, flags in result.flags.items():
        await session.execute(
            sa.text("UPDATE paper_dates SET flags = flags || CAST(:f AS text[]) WHERE id = :id"),
            {"f": list(flags), "id": claim_id},
        )
    first = result.first_public
    await session.execute(
        sa.text(
            "UPDATE papers SET date_confidence = :c, first_public_appearance = :fpa, "
            "first_public_basis = :b, first_public_precision = :pr, "
            "first_public_manifestation_id = :m, first_public_event_id = :e, "
            "candidate_public_date = :cand WHERE id = :p"
        ),
        {
            "c": result.confidence.value,
            "fpa": first.value if first else None,
            "b": result.basis.value if first and result.basis else None,
            "pr": first.precision.value if first else None,
            "m": first.manifestation_id if first else None,
            "e": first.id if first else None,
            "cand": result.candidate_public_date,
            "p": paper_id,
        },
    )
    return result
