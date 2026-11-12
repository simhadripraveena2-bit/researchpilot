"""Release types of a project's papers in a date window, and the display time zone."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from researchpilot.api.deps import ProjectScoped, Session, User
from researchpilot.core.errors import ValidationFailed
from researchpilot.domain.enums import (
    NEW_RESEARCH,
    DateConfidence,
    DateEvent,
    DatePrecision,
    FirstPublicBasis,
    ReleaseType,
    TimezoneSource,
)
from researchpilot.domain.windows import (
    DEFAULT_DAYS,
    Window,
    display,
    from_dates,
    from_instants,
    rolling,
    zone,
)
from researchpilot.services.dates.release_types import Release
from researchpilot.services.dates.releases import counts, project_releases
from researchpilot.services.dates.resolver import DateClaim

router = APIRouter(tags=["releases"])


class LocalTime(BaseModel):
    """A stored value as the UI shows it (D23): timestamps in the user's zone, date-only values
    as the same calendar date everywhere."""

    text: str
    local: str
    utc: str
    zone: str | None
    date_only: bool


class WindowOut(BaseModel):
    kind: str
    start: datetime  # UTC, inclusive
    end: datetime  # UTC, exclusive
    start_local: LocalTime
    end_local: LocalTime
    timezone: str


class EventOut(BaseModel):
    id: uuid.UUID
    event: DateEvent
    value: datetime
    precision: DatePrecision
    version: int | None
    is_primary: bool
    reporting_source: str
    upstream_source: str
    manifestation_id: uuid.UUID
    local: LocalTime


class ReleaseEntry(BaseModel):
    paper_id: uuid.UUID
    title: str
    release_type: ReleaseType
    is_new_research: bool
    event: EventOut
    boundary_day: bool
    confidence: DateConfidence
    basis: FirstPublicBasis | None
    first_public: EventOut | None
    publication_type: str
    manifestation_kind: str
    server_or_venue: str
    peer_review_label: str
    reason: str
    notes: list[str]


class ReleasesOut(BaseModel):
    window: WindowOut
    counts: dict[str, int]
    new_research: int
    entries: list[ReleaseEntry]


class Preferences(BaseModel):
    timezone: str = Field(examples=["Europe/Berlin"])
    timezone_source: TimezoneSource = TimezoneSource.USER


def local_time(value: datetime, precision: DatePrecision, tz_name: str) -> LocalTime:
    return LocalTime(**display(value, precision, zone(tz_name)).__dict__)


def _event(c: DateClaim, tz: str) -> EventOut:
    return EventOut(
        id=c.id,
        event=c.event,
        value=c.value,
        precision=c.precision,
        version=c.version,
        is_primary=c.is_primary,
        reporting_source=c.reporting_source.value,
        upstream_source=c.upstream_source.value,
        manifestation_id=c.manifestation_id,
        local=local_time(c.value, c.precision, tz),
    )


def _parse_bound(text: str) -> date | datetime:
    try:
        return (
            date.fromisoformat(text)
            if len(text) == 10
            else datetime.fromisoformat(text.replace("Z", "+00:00"))
        )
    except ValueError as exc:
        raise ValidationFailed(f"not a date or timestamp: {text!r}") from exc


def window_from_query(
    now: datetime, days: int | None, start: str | None, end: str | None
) -> Window:
    if start is None and end is None:
        return rolling(now, days or DEFAULT_DAYS)
    if start is None or end is None or days is not None:
        raise ValidationFailed("give either days, or both from and to")
    first, last = _parse_bound(start), _parse_bound(end)
    if isinstance(first, datetime) and isinstance(last, datetime):
        return from_instants(first, last)
    if type(first) is date and type(last) is date:
        return from_dates(first, last)
    raise ValidationFailed("from and to must both be dates or both be timestamps")


async def user_timezone(session: Any, user_id: uuid.UUID) -> str:
    tz = (
        await session.execute(sa.text("SELECT timezone FROM users WHERE id = :u"), {"u": user_id})
    ).scalar_one_or_none()
    return str(tz or "UTC")


@router.get("/projects/{project_id}/releases")
async def releases(
    scope: ProjectScoped,
    session: Session,
    request: Request,
    days: Annotated[int | None, Query(ge=1, le=366)] = None,
    start: Annotated[str | None, Query(alias="from", description="UTC date or timestamp")] = None,
    end: Annotated[
        str | None, Query(alias="to", description="UTC date (inclusive) or timestamp (exclusive)")
    ] = None,
    tz: Annotated[str | None, Query(description="IANA zone for display only")] = None,
    release_type: Annotated[list[ReleaseType] | None, Query()] = None,
) -> ReleasesOut:
    """Why each project paper appears in the window (default: the rolling 7 days, UTC).
    The display zone never changes which papers are in the window."""
    now = request.app.state.clock.now()
    window = window_from_query(now, days, start, end)
    tz_name = tz or await user_timezone(session, scope.user_id)
    zone(tz_name)  # validate
    found = await project_releases(session, scope.project_id, window, now)
    if release_type:
        found = [f for f in found if f[2].release_type in release_type]
    return ReleasesOut(
        window=WindowOut(
            kind=window.kind,
            start=window.start,
            end=window.end,
            timezone=tz_name,
            start_local=local_time(window.start, DatePrecision.TIMESTAMP, tz_name),
            end_local=local_time(window.end, DatePrecision.TIMESTAMP, tz_name),
        ),
        counts=counts(found),
        new_research=sum(1 for _, _, r in found if r.release_type in NEW_RESEARCH),
        entries=[_entry(pid, title, r, tz_name) for pid, title, r in found],
    )


def _entry(paper_id: uuid.UUID, title: str, r: Release, tz: str) -> ReleaseEntry:
    return ReleaseEntry(
        paper_id=paper_id,
        title=title,
        release_type=r.release_type,
        is_new_research=r.is_new_research,
        event=_event(r.event, tz),
        boundary_day=r.boundary_day,
        confidence=r.confidence,
        basis=r.basis,
        first_public=_event(r.first_public, tz) if r.first_public else None,
        publication_type=r.manifestation.publication_type.value,
        manifestation_kind=r.manifestation.kind.value,
        server_or_venue=r.manifestation.server_or_venue,
        peer_review_label=r.manifestation.peer_review_label.value,
        reason=r.reason,
        notes=list(r.notes),
    )


@router.get("/me/preferences")
async def get_preferences(session: Session, user: User) -> Preferences:
    row = (
        await session.execute(
            sa.text("SELECT timezone, timezone_source FROM users WHERE id = :u"), {"u": user.id}
        )
    ).one()
    return Preferences(timezone=row.timezone, timezone_source=TimezoneSource(row.timezone_source))


@router.put("/me/preferences")
async def put_preferences(body: Preferences, session: Session, user: User) -> Preferences:
    zone(body.timezone)  # IANA names only
    await session.execute(
        sa.text("UPDATE users SET timezone = :tz, timezone_source = :src WHERE id = :u"),
        {"tz": body.timezone, "src": body.timezone_source.value, "u": user.id},
    )
    return body
