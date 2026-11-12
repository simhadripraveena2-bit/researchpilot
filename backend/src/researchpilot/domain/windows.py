"""Date windows and local-time display (ARCHITECTURE §4.8.6, decision D23).

* **UTC only for membership.** A window is ``[start, end)`` in UTC: start inclusive, end
  exclusive. The default is the rolling 7 days ``[now - 7 x 24 h, now)``. Custom ranges are UTC
  calendar days (``from``..``to`` inclusive -> ``[from 00:00Z, to+1 00:00Z)``) or explicit
  instants. The user's time zone **never** changes which items are in a window.
* **Date-only values** (precision ``day``) are the UTC day ``[D 00:00, D+1 00:00)``: in the
  window if that day overlaps it; a day only partly inside is flagged ``boundary_day``.
* **Month/year precision** never falls inside a window of 31 days or less; in longer windows
  only a period entirely inside counts.
* **Display** converts timestamps to the user's IANA zone (DST via the zone database) and shows
  date-only values as the same calendar date in every zone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from researchpilot.core.errors import ValidationFailed
from researchpilot.domain.enums import DatePrecision

DEFAULT_DAYS = 7
MAX_WINDOW_DAYS = 366
COARSE_LIMIT = timedelta(days=31)


@dataclass(frozen=True)
class Window:
    start: datetime  # UTC, inclusive
    end: datetime  # UTC, exclusive
    kind: str  # "rolling" | "custom"

    def __post_init__(self) -> None:
        for value in (self.start, self.end):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError("window bounds must be UTC")
        if self.end <= self.start:
            raise ValidationFailed("the window end must be after its start")
        if self.end - self.start > timedelta(days=MAX_WINDOW_DAYS):
            raise ValidationFailed(f"a window can span at most {MAX_WINDOW_DAYS} days")

    @property
    def length(self) -> timedelta:
        return self.end - self.start


def rolling(now: datetime, days: int = DEFAULT_DAYS) -> Window:
    if not 1 <= days <= MAX_WINDOW_DAYS:
        raise ValidationFailed(f"days must be between 1 and {MAX_WINDOW_DAYS}")
    end = now.astimezone(UTC)
    return Window(end - timedelta(days=days), end, "rolling")


def from_dates(first: date, last: date) -> Window:
    """UTC calendar days ``first``..``last`` inclusive."""
    if last < first:
        raise ValidationFailed("the range ends before it starts")
    start = datetime.combine(first, time(0), UTC)
    return Window(start, datetime.combine(last + timedelta(days=1), time(0), UTC), "custom")


def from_instants(start: datetime, end: datetime) -> Window:
    """Explicit instants (any offset); compared as UTC instants."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValidationFailed("timestamps need a time zone offset (e.g. Z or +01:00)")
    return Window(start.astimezone(UTC), end.astimezone(UTC), "custom")


@dataclass(frozen=True)
class Placement:
    relation: str  # "before" | "inside" | "after" | "straddles" (coarse value overlapping)
    boundary_day: bool = False

    @property
    def inside(self) -> bool:
        return self.relation == "inside"


def period(value: datetime, precision: DatePrecision) -> tuple[datetime, datetime]:
    """The UTC interval a stored value stands for (date-only values are UTC days)."""
    v = value.astimezone(UTC)
    if precision is DatePrecision.TIMESTAMP:
        return v, v
    if precision is DatePrecision.DAY:
        start = datetime(v.year, v.month, v.day, tzinfo=UTC)
        return start, start + timedelta(days=1)
    if precision is DatePrecision.MONTH:
        start = datetime(v.year, v.month, 1, tzinfo=UTC)
        nxt = datetime(v.year + (v.month == 12), v.month % 12 + 1, 1, tzinfo=UTC)
        return start, nxt
    return datetime(v.year, 1, 1, tzinfo=UTC), datetime(v.year + 1, 1, 1, tzinfo=UTC)


def place(value: datetime, precision: DatePrecision, window: Window) -> Placement:
    lo, hi = period(value, precision)
    if precision is DatePrecision.TIMESTAMP:
        if lo < window.start:
            return Placement("before")
        return Placement("inside") if lo < window.end else Placement("after")
    if hi <= window.start:
        return Placement("before")
    if lo >= window.end:
        return Placement("after")
    if precision is DatePrecision.DAY:
        partial = lo < window.start or hi > window.end
        return Placement("inside", boundary_day=partial)
    # Month / year: never inside a window of 31 days or less; in longer windows only a
    # period entirely inside counts. A coarse period overlapping the window otherwise is
    # "straddles": neither inside nor clearly before/after (callers treat it as uncertain).
    if window.length > COARSE_LIMIT and lo >= window.start and hi <= window.end:
        return Placement("inside")
    return Placement("straddles")


# --- display ------------------------------------------------------------------------------


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationFailed(
            f"unknown time zone {name!r} (use an IANA name such as Europe/Berlin)"
        ) from exc


@dataclass(frozen=True)
class LocalDisplay:
    text: str  # what the UI shows
    local: str  # ISO 8601 in the user's zone (timestamps) or the plain date/month/year
    utc: str  # ISO 8601 UTC (timestamps) or the plain date/month/year
    zone: str | None  # abbreviation, e.g. CET / CEST (timestamps only)
    date_only: bool


def display(value: datetime, precision: DatePrecision, tz: ZoneInfo) -> LocalDisplay:
    if precision is DatePrecision.TIMESTAMP:
        local = value.astimezone(tz)
        abbreviation = local.tzname() or tz.key
        return LocalDisplay(
            text=f"{local:%Y-%m-%d %H:%M} {abbreviation}",
            local=local.isoformat(),
            utc=value.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            zone=abbreviation,
            date_only=False,
        )
    v = value.astimezone(UTC)  # date-only values are never shifted between zones
    text = {
        DatePrecision.DAY: f"{v:%Y-%m-%d}",
        DatePrecision.MONTH: f"{v:%Y-%m}",
        DatePrecision.YEAR: f"{v:%Y}",
    }[precision]
    return LocalDisplay(text=text, local=text, utc=text, zone=None, date_only=True)
