"""Date Resolver confidence rules (D28 revised), table-driven (G-LATEST-DATES style cases)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from researchpilot.domain.enums import (
    DateConfidence as C,
)
from researchpilot.domain.enums import (
    DateEvent as E,
)
from researchpilot.domain.enums import (
    DatePrecision as P,
)
from researchpilot.domain.enums import (
    FirstPublicBasis as B,
)
from researchpilot.domain.enums import (
    ReportingSource as R,
)
from researchpilot.domain.enums import (
    UpstreamSource as U,
)
from researchpilot.services.dates.resolver import DateClaim, resolve

NOW = datetime(2026, 11, 11, 12, tzinfo=UTC)
ARXIV_M, JOURNAL_M, BIORXIV_M = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def claim(
    event: E,
    when: str,
    *,
    m: uuid.UUID = ARXIV_M,
    primary: bool = True,
    source: R = R.ARXIV_API,
    upstream: U = U.UNKNOWN,
    precision: P | None = None,
    version: int | None = None,
) -> DateClaim:
    value = datetime.fromisoformat(when if "T" in when else when + "T00:00:00+00:00")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return DateClaim(
        uuid.uuid4(),
        m,
        event,
        value,
        precision or (P.TIMESTAMP if "T" in when else P.DAY),
        primary,
        source,
        upstream,
        version,
    )


SUBMITTED = claim(E.PREPRINT_SUBMITTED, "2026-11-08T21:14:00+00:00", version=1)
ANNOUNCED = claim(
    E.PREPRINT_ANNOUNCED, "2026-11-10", source=R.ARXIV_ANNOUNCEMENT_FEED, upstream=U.ARXIV
)


def test_arxiv_without_announcement_is_submission_only() -> None:
    r = resolve([SUBMITTED], NOW)
    assert (r.confidence, r.basis, r.first_public) == (C.VERIFIED, B.SUBMISSION_ONLY, SUBMITTED)
    assert r.candidate_public_date is None


def test_captured_announcement_replaces_submission_only() -> None:
    r = resolve([SUBMITTED, ANNOUNCED], NOW)
    assert (r.confidence, r.basis, r.first_public) == (C.VERIFIED, B.ANNOUNCED, ANNOUNCED)


def test_revision_is_never_a_first_appearance() -> None:
    v2 = claim(E.VERSION_SUBMITTED, "2026-11-09T10:00:00+00:00", version=2)
    v2_posted = claim(
        E.PREPRINT_POSTED,
        "2026-11-09",
        m=BIORXIV_M,
        source=R.BIORXIV_API,
        upstream=U.BIORXIV,
        version=2,
    )
    assert resolve([v2, v2_posted], NOW).confidence is C.UNCERTAIN


def test_journal_version_of_an_earlier_preprint_keeps_the_preprint_date() -> None:
    journal = claim(
        E.PUBLISHED_ONLINE, "2027-01-05", m=JOURNAL_M, source=R.CROSSREF, upstream=U.CROSSREF
    )
    r = resolve([SUBMITTED, ANNOUNCED, journal], datetime(2027, 1, 6, tzinfo=UTC))
    assert r.first_public == ANNOUNCED and r.basis is B.ANNOUNCED


def test_journal_only_paper_is_verified_from_crossref() -> None:
    online = claim(
        E.PUBLISHED_ONLINE, "2026-11-03", m=JOURNAL_M, source=R.CROSSREF, upstream=U.CROSSREF
    )
    issue = claim(
        E.ISSUE_PUBLISHED, "2026-12-01", m=JOURNAL_M, source=R.CROSSREF, upstream=U.CROSSREF
    )
    r = resolve([online, issue], NOW)
    assert (r.confidence, r.basis, r.first_public) == (C.VERIFIED, B.PUBLISHED_ONLINE, online)


def test_metadata_and_index_dates_never_make_a_paper_public() -> None:
    claims = [
        claim(E.METADATA_DEPOSITED, "2026-11-10", m=JOURNAL_M, source=R.CROSSREF),
        claim(E.METADATA_INDEXED, "2026-11-10", m=JOURNAL_M, source=R.CROSSREF),
        claim(E.INDEX_CREATED, "2026-11-10", m=JOURNAL_M, primary=False, source=R.OPENALEX),
        claim(E.ACCEPTED, "2026-11-01", m=JOURNAL_M, source=R.CROSSREF),
    ]
    assert resolve(claims, NOW).confidence is C.UNCERTAIN


def test_secondary_only_single_source_is_unconfirmed() -> None:
    oa = claim(
        E.REPORTED_PUBLICATION_DATE, "2026-11-09", m=JOURNAL_M, primary=False, source=R.OPENALEX
    )
    r = resolve([oa], NOW)
    assert (r.confidence, r.first_public, r.candidate_public_date) == (
        C.SINGLE_SOURCE,
        None,
        date(2026, 11, 9),
    )


def test_secondary_agreement_without_known_upstream_is_not_corroboration() -> None:
    oa = claim(
        E.REPORTED_PUBLICATION_DATE, "2026-11-09", m=JOURNAL_M, primary=False, source=R.OPENALEX
    )
    s2 = claim(
        E.REPORTED_PUBLICATION_DATE,
        "2026-11-09",
        m=JOURNAL_M,
        primary=False,
        source=R.SEMANTIC_SCHOLAR,
    )
    r = resolve([oa, s2], NOW)
    assert (r.confidence, r.first_public) == (C.SOURCE_AGREEMENT, None)


def test_independent_upstreams_corroborate() -> None:
    via_crossref = claim(
        E.PUBLISHED_ONLINE,
        "2026-11-09",
        m=JOURNAL_M,
        primary=False,
        source=R.OPENALEX,
        upstream=U.CROSSREF,
    )
    via_pubmed = claim(
        E.PUBLISHED_ONLINE,
        "2026-11-10",
        m=JOURNAL_M,
        primary=False,
        source=R.SEMANTIC_SCHOLAR,
        upstream=U.PUBMED,
    )
    r = resolve([via_crossref, via_pubmed], NOW)
    assert (r.confidence, r.first_public) == (C.CORROBORATED, via_crossref)


def test_shared_upstream_is_not_independent() -> None:
    a = claim(
        E.PUBLISHED_ONLINE,
        "2026-11-09",
        m=JOURNAL_M,
        primary=False,
        source=R.OPENALEX,
        upstream=U.CROSSREF,
    )
    b = claim(
        E.PUBLISHED_ONLINE,
        "2026-11-09",
        m=JOURNAL_M,
        primary=False,
        source=R.SEMANTIC_SCHOLAR,
        upstream=U.CROSSREF,
    )
    assert resolve([a, b], NOW).confidence is C.SOURCE_AGREEMENT


def test_conflicting_primary_dates() -> None:
    a = claim(E.PUBLISHED_ONLINE, "2026-11-01", m=JOURNAL_M, source=R.CROSSREF)
    b = claim(E.PUBLISHED_ONLINE, "2026-11-05", m=JOURNAL_M, source=R.CROSSREF)
    r = resolve([a, b], NOW)
    assert (r.confidence, r.first_public, r.candidate_public_date) == (
        C.CONFLICTING,
        None,
        date(2026, 11, 1),
    )


def test_conflicting_secondary_dates() -> None:
    a = claim(
        E.REPORTED_PUBLICATION_DATE, "2026-11-01", m=JOURNAL_M, primary=False, source=R.OPENALEX
    )
    b = claim(
        E.REPORTED_PUBLICATION_DATE,
        "2026-11-09",
        m=JOURNAL_M,
        primary=False,
        source=R.SEMANTIC_SCHOLAR,
    )
    assert resolve([a, b], NOW).confidence is C.CONFLICTING


def test_secondary_disagreeing_with_primary_is_flagged_and_primary_stands() -> None:
    online = claim(E.PUBLISHED_ONLINE, "2026-11-03", m=JOURNAL_M, source=R.CROSSREF)
    oa = claim(
        E.REPORTED_PUBLICATION_DATE, "2026-01-01", m=JOURNAL_M, primary=False, source=R.OPENALEX
    )
    r = resolve([online, oa], NOW)
    assert r.first_public == online and r.confidence is C.VERIFIED
    assert r.flags[oa.id] == ("disagrees_with_primary",)


@pytest.mark.parametrize("precision", [P.MONTH, P.YEAR])
def test_month_or_year_precision_is_uncertain(precision: P) -> None:
    c = claim(E.PUBLISHED_ONLINE, "2026-11-01", m=JOURNAL_M, source=R.CROSSREF, precision=precision)
    assert resolve([c], NOW).confidence is C.UNCERTAIN


def test_future_dates_are_flagged_and_ignored() -> None:
    future = claim(E.PUBLISHED_ONLINE, "2026-11-20", m=JOURNAL_M, source=R.CROSSREF)
    r = resolve([future], NOW)
    assert r.confidence is C.UNCERTAIN and r.flags[future.id] == ("future_date",)


def test_tomorrow_is_within_tolerance() -> None:
    tomorrow = claim(E.PUBLISHED_ONLINE, "2026-11-12", m=JOURNAL_M, source=R.CROSSREF)
    assert resolve([tomorrow], NOW).confidence is C.VERIFIED


def test_no_claims_is_uncertain() -> None:
    assert resolve([], NOW).confidence is C.UNCERTAIN


# --- regression: submission_only never competes with a real public event -----------------

NOV8_SUBMITTED = claim(E.PREPRINT_SUBMITTED, "2026-11-08T21:14:00+00:00", version=1)


def test_journal_publication_beats_an_earlier_unannounced_arxiv_submission() -> None:
    """arXiv v1 submitted Nov 8, journal online Nov 15, no announcement captured: the
    journal's public event decides; the submission is not used as the first appearance."""
    journal = claim(
        E.PUBLISHED_ONLINE, "2026-11-15", m=JOURNAL_M, source=R.CROSSREF, upstream=U.CROSSREF
    )
    r = resolve([NOV8_SUBMITTED, journal], datetime(2026, 11, 16, tzinfo=UTC))
    assert (r.confidence, r.basis, r.first_public) == (C.VERIFIED, B.PUBLISHED_ONLINE, journal)
    assert "earlier arXiv submission" in r.reason
    assert NOV8_SUBMITTED.id not in r.flags  # the submission event is untouched


def test_secondary_public_claim_beats_the_submission_fallback() -> None:
    """arXiv v1 submitted Nov 8, then only OpenAlex reports a publication date: the normal
    secondary rules apply (single source -> unconfirmed), not submission_only."""
    openalex = claim(
        E.REPORTED_PUBLICATION_DATE, "2026-11-12", m=JOURNAL_M, primary=False, source=R.OPENALEX
    )
    r = resolve([NOV8_SUBMITTED, openalex], NOW)
    assert (r.confidence, r.basis, r.first_public) == (C.SINGLE_SOURCE, None, None)
    assert r.candidate_public_date == date(2026, 11, 12)


def test_secondary_agreement_also_beats_the_submission_fallback() -> None:
    oa = claim(
        E.REPORTED_PUBLICATION_DATE, "2026-11-10", m=JOURNAL_M, primary=False, source=R.OPENALEX
    )
    s2 = claim(
        E.REPORTED_PUBLICATION_DATE,
        "2026-11-10",
        m=JOURNAL_M,
        primary=False,
        source=R.SEMANTIC_SCHOLAR,
    )
    assert resolve([NOV8_SUBMITTED, oa, s2], NOW).confidence is C.SOURCE_AGREEMENT


def test_month_precision_public_claim_also_rules_out_the_fallback() -> None:
    """A public event that cannot be dated to the day still exists: date uncertain."""
    issue = claim(
        E.ISSUE_PUBLISHED, "2026-11-01", m=JOURNAL_M, source=R.CROSSREF, precision=P.MONTH
    )
    r = resolve([NOV8_SUBMITTED, issue], NOW)
    assert (r.confidence, r.first_public, r.candidate_public_date) == (C.UNCERTAIN, None, None)


def test_future_public_claim_does_not_rule_out_the_fallback() -> None:
    future = claim(E.PUBLISHED_ONLINE, "2027-03-01", m=JOURNAL_M, source=R.CROSSREF)
    r = resolve([NOV8_SUBMITTED, future], NOW)
    assert (r.basis, r.first_public) == (B.SUBMISSION_ONLY, NOV8_SUBMITTED)


def test_metadata_dates_do_not_rule_out_the_fallback() -> None:
    deposited = claim(E.METADATA_DEPOSITED, "2026-11-09", m=JOURNAL_M, source=R.CROSSREF)
    r = resolve([NOV8_SUBMITTED, deposited], NOW)
    assert (r.basis, r.first_public) == (B.SUBMISSION_ONLY, NOV8_SUBMITTED)
