"""arXiv Atom parsing against recorded responses (tests/fixtures/sources/arxiv, 2026-11-11)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from researchpilot.integrations.arxiv import parse_feed
from researchpilot.integrations.base import SourceError

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sources" / "arxiv"


def feed(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_new_style_entry() -> None:
    [entry] = parse_feed(feed("api_1706.03762.xml"))
    assert (entry.arxiv_id, entry.latest_version) == ("1706.03762", 7)
    assert entry.title == "Attention Is All You Need"
    assert entry.authors[0].name == "Ashish Vaswani" and len(entry.authors) == 8
    # <published> = v1 submission; <updated> = latest (v7) submission
    assert entry.submitted_v1 == datetime(2017, 6, 12, 17, 57, 34, tzinfo=UTC)
    assert entry.submitted_latest == datetime(2023, 8, 2, 0, 41, 18, tzinfo=UTC)
    assert entry.primary_category == "cs.CL" and entry.categories == ("cs.CL", "cs.LG")
    assert entry.doi is None and entry.journal_ref is None
    assert entry.pdf_url == "https://arxiv.org/pdf/1706.03762v7"


def test_versioned_query_reports_that_versions_submission_as_updated() -> None:
    [entry] = parse_feed(feed("api_1706.03762v2.xml"))
    assert entry.latest_version == 2
    assert entry.submitted_latest == datetime(2017, 6, 19, 16, 49, 45, tzinfo=UTC)
    assert entry.submitted_v1 == datetime(2017, 6, 12, 17, 57, 34, tzinfo=UTC)


def test_old_style_entry_with_author_supplied_journal_link() -> None:
    [entry] = parse_feed(feed("api_hep-th_9711200.xml"))
    assert (entry.arxiv_id, entry.latest_version) == ("hep-th/9711200", 3)
    assert entry.doi == "10.1023/A:1026654312961"
    assert entry.journal_ref == "Adv.Theor.Math.Phys.2:231-252,1998"


def test_submission_can_precede_the_id_month_by_weeks() -> None:
    """2411.00001 was submitted on 2024-10-08 but numbered (announced) in November:
    the submission timestamp is not the public release date."""
    [entry] = parse_feed(feed("api_2411.00001.xml"))
    assert entry.arxiv_id == "2411.00001"
    assert entry.submitted_v1.date().isoformat() == "2024-10-08"


def test_unknown_id_returns_no_entries() -> None:
    assert parse_feed(feed("api_not_found_2401.99999.xml")) == []


def test_multiple_ids_in_one_query() -> None:
    ids = {e.arxiv_id for e in parse_feed(feed("api_multi_two_ids.xml"))}
    assert ids == {"1706.03762", "hep-th/9711200"}


@pytest.mark.parametrize(
    "name", ["api_hep-th_9711200v2.xml", "api_multi_with_old_style_version.xml"]
)
def test_error_entries_are_errors_even_with_http_200(name: str) -> None:
    with pytest.raises(SourceError, match="arXiv reported an error"):
        parse_feed(feed(name))
