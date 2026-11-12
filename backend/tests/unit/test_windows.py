"""Date windows (R1-48), time-zone display and DST (R1-47), D23."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from researchpilot.core.errors import ValidationFailed
from researchpilot.domain.enums import DatePrecision as P
from researchpilot.domain.windows import (
    display,
    from_dates,
    from_instants,
    place,
    rolling,
    zone,
)

NOW = datetime(2026, 11, 12, 15, 30, tzinfo=UTC)
W = rolling(NOW)  # [2026-11-05 15:30Z, 2026-11-12 15:30Z)


def test_default_is_the_rolling_seven_days() -> None:
    assert (W.start, W.end, W.kind) == (NOW - timedelta(hours=168), NOW, "rolling")


def test_timestamp_boundaries() -> None:
    assert place(NOW - timedelta(hours=168), P.TIMESTAMP, W).inside  # start inclusive
    assert place(NOW - timedelta(hours=168, seconds=1), P.TIMESTAMP, W).relation == "before"
    assert place(NOW, P.TIMESTAMP, W).relation == "after"  # end exclusive
    assert place(NOW - timedelta(seconds=1), P.TIMESTAMP, W).inside


def test_date_only_values_on_boundary_days_are_included_and_flagged() -> None:
    start_day = place(datetime(2026, 11, 5, tzinfo=UTC), P.DAY, W)
    end_day = place(datetime(2026, 11, 12, tzinfo=UTC), P.DAY, W)
    middle = place(datetime(2026, 11, 8, tzinfo=UTC), P.DAY, W)
    assert (start_day.inside, start_day.boundary_day) == (True, True)
    assert (end_day.inside, end_day.boundary_day) == (True, True)
    assert (middle.inside, middle.boundary_day) == (True, False)
    assert place(datetime(2026, 11, 4, tzinfo=UTC), P.DAY, W).relation == "before"
    assert place(datetime(2026, 11, 13, tzinfo=UTC), P.DAY, W).relation == "after"


def test_month_and_year_precision_never_fall_in_short_windows() -> None:
    for precision in (P.MONTH, P.YEAR):
        assert not place(datetime(2026, 11, 1, tzinfo=UTC), precision, W).inside
    long = from_dates(date(2026, 1, 1), date(2026, 12, 31))
    assert place(datetime(2026, 6, 1, tzinfo=UTC), P.MONTH, long).inside
    assert place(datetime(2026, 1, 1, tzinfo=UTC), P.YEAR, long).inside
    partial = from_dates(date(2026, 5, 15), date(2026, 7, 31))  # > 31 days
    assert place(datetime(2026, 5, 1, tzinfo=UTC), P.MONTH, partial).relation == "straddles"


def test_custom_ranges_are_utc_days_or_instants() -> None:
    w = from_dates(date(2026, 11, 1), date(2026, 11, 7))
    assert (w.start, w.end) == (
        datetime(2026, 11, 1, tzinfo=UTC),
        datetime(2026, 11, 8, tzinfo=UTC),
    )
    berlin = from_instants(
        datetime(2026, 11, 1, 1, tzinfo=ZoneInfo("Europe/Berlin")),
        datetime(2026, 11, 2, 1, tzinfo=ZoneInfo("Europe/Berlin")),
    )
    assert berlin.start == datetime(2026, 11, 1, 0, tzinfo=UTC)  # same instant, in UTC
    with pytest.raises(ValidationFailed):
        from_dates(date(2026, 11, 7), date(2026, 11, 1))
    with pytest.raises(ValidationFailed):
        from_dates(date(2025, 1, 1), date(2026, 12, 31))  # more than 366 days
    with pytest.raises(ValidationFailed):
        from_instants(datetime(2026, 11, 1), datetime(2026, 11, 2))  # naive
    with pytest.raises(ValidationFailed):
        rolling(NOW, days=0)


ZONES = ["UTC", "Europe/Berlin", "America/Los_Angeles", "Asia/Kolkata", "Pacific/Kiritimati"]


@pytest.mark.parametrize(
    ("instant", "tz", "text"),
    [
        (datetime(2026, 11, 8, 20, 14, tzinfo=UTC), "Europe/Berlin", "2026-11-08 21:14 CET"),
        (datetime(2026, 7, 8, 20, 14, tzinfo=UTC), "Europe/Berlin", "2026-07-08 22:14 CEST"),
        # Europe: DST ended 2026-10-25 01:00 UTC
        (datetime(2026, 10, 25, 0, 59, tzinfo=UTC), "Europe/Berlin", "2026-10-25 02:59 CEST"),
        (datetime(2026, 10, 25, 1, 0, tzinfo=UTC), "Europe/Berlin", "2026-10-25 02:00 CET"),
        # North America: DST ended 2026-11-01 09:00 UTC; began 2026-03-08 10:00 UTC
        (datetime(2026, 11, 1, 8, 59, tzinfo=UTC), "America/Los_Angeles", "2026-11-01 01:59 PDT"),
        (datetime(2026, 11, 1, 9, 0, tzinfo=UTC), "America/Los_Angeles", "2026-11-01 01:00 PST"),
        (datetime(2026, 3, 8, 10, 0, tzinfo=UTC), "America/Los_Angeles", "2026-03-08 03:00 PDT"),
        (datetime(2026, 11, 8, 20, 14, tzinfo=UTC), "Asia/Kolkata", "2026-11-09 01:44 IST"),
        (datetime(2026, 11, 8, 20, 14, tzinfo=UTC), "Pacific/Kiritimati", "2026-11-09 10:14 +14"),
    ],
)
def test_timestamps_display_in_the_users_zone(instant: datetime, tz: str, text: str) -> None:
    shown = display(instant, P.TIMESTAMP, zone(tz))
    assert shown.text == text and not shown.date_only
    assert shown.utc.endswith("Z")


@pytest.mark.parametrize("tz", ZONES)
def test_date_only_values_show_the_same_date_everywhere(tz: str) -> None:
    day = datetime(2026, 11, 5, tzinfo=UTC)
    assert display(day, P.DAY, zone(tz)).text == "2026-11-05"
    assert display(day, P.MONTH, zone(tz)).text == "2026-11"
    assert display(day, P.YEAR, zone(tz)).text == "2026"


def test_unknown_zone_is_rejected() -> None:
    with pytest.raises(ValidationFailed):
        zone("Mars/Olympus")


@given(
    st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2040, 1, 1)),
    st.sampled_from([P.TIMESTAMP, P.DAY, P.MONTH, P.YEAR]),
    st.sampled_from(ZONES),
    st.sampled_from(ZONES),
)
def test_zone_never_changes_window_membership(
    value: datetime, precision: P, z1: str, z2: str
) -> None:
    """Membership is computed in UTC; displaying in two zones cannot change it."""
    stamp = value.replace(tzinfo=UTC)
    in_z1 = place(stamp.astimezone(ZoneInfo(z1)), precision, W)
    in_z2 = place(stamp.astimezone(ZoneInfo(z2)), precision, W)
    assert in_z1 == in_z2
