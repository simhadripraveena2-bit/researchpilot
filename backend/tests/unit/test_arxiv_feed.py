"""arXiv announcement feed parsing (recorded 2026-11-11)."""

from __future__ import annotations

from collections import Counter
from datetime import date

import pytest

from researchpilot.integrations.arxiv_feed import announcement_day, parse_feed
from researchpilot.integrations.base import SourceError
from tests.fixtures.source_transport import SOURCES

RSS = SOURCES / "arxiv_rss"


def test_all_announce_types_with_versions() -> None:
    day, items = parse_feed((RSS / "rss_q-bio.QM.xml").read_text())
    assert day == date(2026, 11, 11)
    assert Counter(i.announce_type for i in items) == {
        "new": 3,
        "cross": 4,
        "replace": 2,
        "replace-cross": 3,
    }
    new = next(i for i in items if i.arxiv_id == "2611.13190")
    assert (new.announce_type, new.version, new.categories[0]) == ("new", 1, "q-bio.QM")
    replace = next(i for i in items if i.arxiv_id == "2604.22997")
    assert (replace.announce_type, replace.version) == ("replace", 2)


def test_empty_feed_still_has_an_announcement_day() -> None:
    assert parse_feed((RSS / "rss_math.HO.xml").read_text()) == (date(2026, 11, 11), [])


def test_announcement_day_is_the_us_eastern_calendar_date() -> None:
    # Midnight US Eastern = 05:00 UTC; the calendar date stays the 11th.
    assert announcement_day("Wed, 11 Nov 2026 00:00:00 -0500") == date(2026, 11, 11)
    assert announcement_day(None) is None
    assert announcement_day("not a date") is None


def test_items_disagreeing_on_the_day_are_an_error() -> None:
    text = (
        (RSS / "rss_cs.DL.xml")
        .read_text()
        .replace(
            "<pubDate>Wed, 11 Nov 2026 00:00:00 -0500</pubDate>\n    <skipDays>",
            "<pubDate>Tue, 10 Nov 2026 00:00:00 -0500</pubDate>\n    <skipDays>",
            1,
        )
    )
    with pytest.raises(SourceError, match="disagree"):
        parse_feed(text)
