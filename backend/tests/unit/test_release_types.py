"""Release-type classification (ARCHITECTURE §4.8.4; EVALUATION §3.8; R1-24, R1-42-R1-48)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from researchpilot.domain.enums import DateConfidence as C
from researchpilot.domain.enums import DateEvent as E
from researchpilot.domain.enums import DatePrecision as P
from researchpilot.domain.enums import ManifestationKind as K
from researchpilot.domain.enums import PeerReviewLabel as L
from researchpilot.domain.enums import PublicationType as T
from researchpilot.domain.enums import ReleaseType as R
from researchpilot.domain.enums import ReportingSource as S
from researchpilot.domain.enums import UpstreamSource as U
from researchpilot.domain.windows import from_dates, rolling
from researchpilot.services.dates.release_types import ManifestationInfo, WorkDates, classify
from researchpilot.services.dates.resolver import DateClaim

NOW = datetime(2026, 11, 12, 15, 30, tzinfo=UTC)
WEEK = rolling(NOW)  # [2026-11-05 15:30Z, 2026-11-12 15:30Z)

ARXIV = ManifestationInfo(
    uuid.uuid4(), K.PREPRINT, T.PREPRINT, "arxiv", L.PREPRINT_NOT_PEER_REVIEWED
)
BIORXIV = ManifestationInfo(
    uuid.uuid4(), K.PREPRINT, T.PREPRINT, "biorxiv", L.PREPRINT_NOT_PEER_REVIEWED
)
JOURNAL = ManifestationInfo(
    uuid.uuid4(), K.PUBLISHED, T.JOURNAL_ARTICLE, "eLife", L.JOURNAL_VERSION
)
VERSIONED = ManifestationInfo(
    uuid.uuid4(), K.PUBLISHED, T.JOURNAL_ARTICLE, "eLife", L.JOURNAL_VERSION
)  # eLife's versioned DOI of the same article
CONFERENCE = ManifestationInfo(
    uuid.uuid4(), K.PUBLISHED, T.CONFERENCE_PAPER, "CVPR", L.JOURNAL_VERSION
)
CORRECTION = ManifestationInfo(uuid.uuid4(), K.PUBLISHED, T.CORRECTION, "PSJ", L.JOURNAL_VERSION)
RETRACTION = ManifestationInfo(uuid.uuid4(), K.PUBLISHED, T.RETRACTION, "JMFNM", L.JOURNAL_VERSION)


def c(
    m: ManifestationInfo,
    event: E,
    when: str,
    *,
    primary: bool = True,
    source: S = S.CROSSREF,
    upstream: U = U.UNKNOWN,
    version: int | None = None,
    precision: P | None = None,
) -> DateClaim:
    value = datetime.fromisoformat(when if "T" in when else when + "T00:00:00+00:00")
    return DateClaim(
        uuid.uuid4(),
        m.id,
        event,
        value,
        precision or (P.TIMESTAMP if "T" in when else P.DAY),
        primary,
        source,
        upstream,
        version,
    )


def work(
    *claims: DateClaim,
    ms: tuple[ManifestationInfo, ...] | None = None,
    checked: frozenset[str] = frozenset({"crossref"}),
) -> WorkDates:
    used = ms or tuple(
        {
            cl.manifestation_id: m
            for m in (ARXIV, BIORXIV, JOURNAL, VERSIONED, CONFERENCE, CORRECTION, RETRACTION)
            for cl in claims
            if cl.manifestation_id == m.id
        }.values()
    )
    return WorkDates(uuid.uuid4(), claims, {m.id: m for m in used}, checked)


def kind(w: WorkDates, window=WEEK):  # type: ignore[no-untyped-def]
    release = classify(w, window, NOW)
    return release.release_type if release else None


ANNOUNCED = c(
    ARXIV, E.PREPRINT_ANNOUNCED, "2026-11-09", source=S.ARXIV_ANNOUNCEMENT_FEED, upstream=U.ARXIV
)
SUBMITTED = c(
    ARXIV,
    E.PREPRINT_SUBMITTED,
    "2026-11-08T21:14:00+00:00",
    source=S.ARXIV_API,
    upstream=U.ARXIV,
    version=1,
)
OLD_SUBMITTED = c(
    ARXIV,
    E.PREPRINT_SUBMITTED,
    "2025-03-02T10:00:00+00:00",
    source=S.ARXIV_API,
    upstream=U.ARXIV,
    version=1,
)
OLD_ANNOUNCED = c(
    ARXIV, E.PREPRINT_ANNOUNCED, "2025-03-04", source=S.ARXIV_ANNOUNCEMENT_FEED, upstream=U.ARXIV
)


# --- new research --------------------------------------------------------------------------


def test_new_preprint_announced_in_the_window() -> None:
    r = classify(work(SUBMITTED, ANNOUNCED), WEEK, NOW)
    assert r is not None and (r.release_type, r.event, r.confidence) == (
        R.NEW_PREPRINT,
        ANNOUNCED,
        C.VERIFIED,
    )
    assert r.is_new_research and r.manifestation.peer_review_label is L.PREPRINT_NOT_PEER_REVIEWED


def test_new_preprint_on_submission_only_is_labelled() -> None:
    r = classify(work(SUBMITTED), WEEK, NOW)
    assert r is not None and r.release_type is R.NEW_PREPRINT
    assert r.basis is not None and r.basis.value == "submission_only"
    assert "announcement not captured" in r.notes[0]


def test_new_biorxiv_preprint() -> None:
    posted = c(
        BIORXIV,
        E.PREPRINT_POSTED,
        "2026-11-10",
        source=S.BIORXIV_API,
        upstream=U.BIORXIV,
        version=1,
    )
    assert kind(work(posted)) is R.NEW_PREPRINT


def test_new_publication_without_any_earlier_version() -> None:
    online = c(JOURNAL, E.PUBLISHED_ONLINE, "2026-11-09", upstream=U.CROSSREF)
    r = classify(work(online, checked=frozenset({"crossref", "openalex"})), WEEK, NOW)
    assert r is not None and r.release_type is R.NEW_PUBLICATION
    assert r.notes == ("No earlier preprint found in: crossref, openalex",)


def test_conference_paper_is_a_new_publication() -> None:
    online = c(CONFERENCE, E.PUBLISHED_ONLINE, "2026-11-09", upstream=U.CROSSREF)
    assert kind(work(online)) is R.NEW_PUBLICATION


# --- never new research --------------------------------------------------------------------


def test_journal_version_of_an_old_preprint_is_never_new() -> None:
    online = c(JOURNAL, E.PUBLISHED_ONLINE, "2026-11-09", upstream=U.CROSSREF)
    r = classify(work(OLD_SUBMITTED, OLD_ANNOUNCED, online), WEEK, NOW)
    assert r is not None and r.release_type is R.PUBLISHED_VERSION_OF_PREPRINT
    assert not r.is_new_research
    assert r.first_public == OLD_ANNOUNCED and r.notes == ("Preprint public since 2025-03-04",)


def test_journal_version_with_duplicate_manifestations_uses_the_earliest() -> None:
    online = c(JOURNAL, E.PUBLISHED_ONLINE, "2026-11-09", upstream=U.CROSSREF)
    versioned = c(VERSIONED, E.PUBLISHED_ONLINE, "2026-11-10", upstream=U.CROSSREF)
    issued = c(JOURNAL, E.ISSUED, "2026-11-09", upstream=U.CROSSREF)
    r = classify(work(OLD_ANNOUNCED, versioned, issued, online), WEEK, NOW)
    assert r is not None and (r.release_type, r.event) == (R.PUBLISHED_VERSION_OF_PREPRINT, online)


def test_journal_in_window_with_unannounced_earlier_preprint_is_uncertain() -> None:
    """Approved resolver rule: the journal date decides the FPA when no preprint public event
    is known - but a known earlier preprint means it is not presented as new research."""
    sub = c(
        ARXIV,
        E.PREPRINT_SUBMITTED,
        "2026-10-01T09:00:00+00:00",
        source=S.ARXIV_API,
        upstream=U.ARXIV,
        version=1,
    )
    online = c(JOURNAL, E.PUBLISHED_ONLINE, "2026-11-09", upstream=U.CROSSREF)
    r = classify(work(sub, online), WEEK, NOW)
    assert r is not None and (r.release_type, r.confidence) == (R.DATE_UNCERTAIN, C.VERIFIED)


def test_revision_of_an_older_paper() -> None:
    v3 = c(
        ARXIV,
        E.VERSION_ANNOUNCED,
        "2026-11-10",
        source=S.ARXIV_ANNOUNCEMENT_FEED,
        upstream=U.ARXIV,
        version=3,
    )
    assert kind(work(OLD_SUBMITTED, OLD_ANNOUNCED, v3)) is R.REVISED_VERSION


def test_revision_with_unconfirmed_first_date_still_needs_primary_older_evidence() -> None:
    """2604.22997 shape: v1 submitted in April (primary), OpenAlex date only, v2 in window."""
    v1 = c(
        ARXIV,
        E.PREPRINT_SUBMITTED,
        "2026-04-24T20:31:36+00:00",
        source=S.ARXIV_API,
        upstream=U.ARXIV,
        version=1,
    )
    openalex = c(ARXIV, E.REPORTED_PUBLICATION_DATE, "2026-04-24", primary=False, source=S.OPENALEX)
    v2 = c(
        ARXIV,
        E.VERSION_ANNOUNCED,
        "2026-11-11",
        source=S.ARXIV_ANNOUNCEMENT_FEED,
        upstream=U.ARXIV,
        version=2,
    )
    r = classify(work(v1, openalex, v2), WEEK, NOW)
    assert r is not None and (r.release_type, r.confidence) == (R.REVISED_VERSION, C.SINGLE_SOURCE)


def test_v1_and_v2_both_in_the_window_is_a_new_preprint() -> None:
    v2 = c(
        ARXIV,
        E.VERSION_ANNOUNCED,
        "2026-11-11",
        source=S.ARXIV_ANNOUNCEMENT_FEED,
        upstream=U.ARXIV,
        version=2,
    )
    assert kind(work(SUBMITTED, ANNOUNCED, v2)) is R.NEW_PREPRINT


def test_newly_indexed_older_paper_is_not_new() -> None:
    created = c(
        JOURNAL, E.INDEX_CREATED, "2026-11-10T00:00:00+00:00", primary=False, source=S.OPENALEX
    )
    old_online = c(JOURNAL, E.PUBLISHED_ONLINE, "2019-08-23", upstream=U.CROSSREF)
    r = classify(work(old_online, created), WEEK, NOW)
    assert r is not None and r.release_type is R.NEWLY_INDEXED_OLDER
    assert r.notes == ("index date reported by openalex",)
    seen = c(
        JOURNAL,
        E.FIRST_SEEN_BY_RESEARCHPILOT,
        "2026-11-11T08:00:00+00:00",
        primary=False,
        source=S.RESEARCHPILOT,
    )
    r2 = classify(work(old_online, seen), WEEK, NOW)
    assert r2 is not None and "first saw it" in r2.notes[0]


def test_newly_seen_paper_without_older_evidence_is_only_uncertain() -> None:
    seen = c(
        JOURNAL,
        E.FIRST_SEEN_BY_RESEARCHPILOT,
        "2026-11-11T08:00:00+00:00",
        primary=False,
        source=S.RESEARCHPILOT,
    )
    assert kind(work(seen)) is R.DATE_UNCERTAIN


@pytest.mark.parametrize("notice", [CORRECTION, RETRACTION])
def test_corrections_and_retractions_are_notices(notice: ManifestationInfo) -> None:
    online = c(notice, E.PUBLISHED_ONLINE, "2026-11-09", upstream=U.CROSSREF)
    r = classify(work(online), WEEK, NOW)
    assert r is not None and r.release_type is R.CORRECTION_NOTICE and not r.is_new_research
    assert notice.publication_type.value in r.reason


def test_metadata_dates_never_place_a_paper() -> None:
    deposited = c(JOURNAL, E.METADATA_DEPOSITED, "2026-11-10T10:00:00+00:00")
    indexed = c(JOURNAL, E.METADATA_INDEXED, "2026-11-11T10:00:00+00:00")
    updated = c(
        JOURNAL, E.METADATA_UPDATED, "2026-11-11T10:00:00+00:00", primary=False, source=S.OPENALEX
    )
    old_online = c(JOURNAL, E.PUBLISHED_ONLINE, "2019-08-23", upstream=U.CROSSREF)
    assert kind(work(old_online, deposited, indexed, updated)) is None


def test_acceptance_in_the_window_is_not_a_release() -> None:
    accepted = c(JOURNAL, E.ACCEPTED, "2026-11-10", upstream=U.CROSSREF)
    old_online = c(JOURNAL, E.PUBLISHED_ONLINE, "2026-12-01", upstream=U.CROSSREF)
    assert kind(work(accepted, old_online)) is None


# --- uncertain, conflicting, incomplete, future ---------------------------------------------


def test_secondary_only_date_in_window_is_uncertain_never_new() -> None:
    openalex = c(
        JOURNAL, E.REPORTED_PUBLICATION_DATE, "2026-11-09", primary=False, source=S.OPENALEX
    )
    r = classify(work(openalex), WEEK, NOW)
    assert r is not None and (r.release_type, r.confidence) == (R.DATE_UNCERTAIN, C.SINGLE_SOURCE)


def test_source_agreement_is_uncertain() -> None:
    a = c(JOURNAL, E.REPORTED_PUBLICATION_DATE, "2026-11-09", primary=False, source=S.OPENALEX)
    b = c(
        JOURNAL, E.REPORTED_PUBLICATION_DATE, "2026-11-09", primary=False, source=S.SEMANTIC_SCHOLAR
    )
    assert classify(work(a, b), WEEK, NOW).confidence is C.SOURCE_AGREEMENT  # type: ignore[union-attr]
    assert kind(work(a, b)) is R.DATE_UNCERTAIN


def test_conflicting_primary_dates_are_uncertain() -> None:
    a = c(JOURNAL, E.PUBLISHED_ONLINE, "2026-11-06", upstream=U.CROSSREF)
    b = c(JOURNAL, E.PUBLISHED_ONLINE, "2026-11-11", upstream=U.CROSSREF)
    r = classify(work(a, b), WEEK, NOW)
    assert r is not None and (r.release_type, r.confidence) == (R.DATE_UNCERTAIN, C.CONFLICTING)


def test_unconfirmed_earlier_preprint_with_journal_in_window_is_uncertain() -> None:
    via_crossref = c(BIORXIV, E.PREPRINT_POSTED, "2025-10-22", primary=False, upstream=U.BIORXIV)
    online = c(JOURNAL, E.PUBLISHED_ONLINE, "2026-11-09", upstream=U.CROSSREF)
    r = classify(work(via_crossref, online), WEEK, NOW)
    assert r is not None and (r.release_type, r.confidence) == (R.DATE_UNCERTAIN, C.CONFLICTING)


def test_month_precision_is_never_in_a_short_window() -> None:
    issue = c(JOURNAL, E.ISSUE_PUBLISHED, "2026-11-01", upstream=U.CROSSREF, precision=P.MONTH)
    assert kind(work(issue)) is None
    long = from_dates(date(2026, 1, 1), date(2026, 11, 30))
    assert kind(work(issue), long) is R.DATE_UNCERTAIN  # entirely inside a long window


def test_future_dates_are_ignored() -> None:
    future = c(JOURNAL, E.PUBLISHED_ONLINE, "2026-12-20", upstream=U.CROSSREF)
    assert kind(work(future)) is None


def test_missing_dates_place_nothing() -> None:
    assert classify(WorkDates(uuid.uuid4(), (), {JOURNAL.id: JOURNAL}), WEEK, NOW) is None


def test_boundary_day_is_reported() -> None:
    posted = c(
        BIORXIV,
        E.PREPRINT_POSTED,
        "2026-11-05",
        source=S.BIORXIV_API,
        upstream=U.BIORXIV,
        version=1,
    )
    r = classify(work(posted), WEEK, NOW)
    assert r is not None and r.release_type is R.NEW_PREPRINT and r.boundary_day


def test_paper_public_before_the_window_with_nothing_new_is_absent() -> None:
    assert kind(work(OLD_SUBMITTED, OLD_ANNOUNCED)) is None


def test_paper_public_after_a_past_window_is_absent() -> None:
    past = from_dates(date(2026, 10, 1), date(2026, 10, 7))
    assert kind(work(SUBMITTED, ANNOUNCED), past) is None


# --- properties --------------------------------------------------------------------------

offsets = st.integers(min_value=-400, max_value=10)


@given(offsets, offsets, offsets)
def test_later_journal_dates_never_make_an_announced_preprint_new(
    pre: int, pub: int, idx: int
) -> None:
    """Whatever the dates, a journal version or index event is never new research if the
    verified preprint announcement is before the window."""
    if pre >= -8:
        pre = -30  # preprint announced well before the window
    day = lambda n: (NOW + timedelta(days=n)).date().isoformat()  # noqa: E731
    announced = c(
        ARXIV, E.PREPRINT_ANNOUNCED, day(pre), source=S.ARXIV_ANNOUNCEMENT_FEED, upstream=U.ARXIV
    )
    online = c(JOURNAL, E.PUBLISHED_ONLINE, day(max(pub, pre + 1)), upstream=U.CROSSREF)
    seen = c(
        JOURNAL,
        E.FIRST_SEEN_BY_RESEARCHPILOT,
        day(idx) + "T00:00:00+00:00",
        primary=False,
        source=S.RESEARCHPILOT,
    )
    r = classify(work(announced, online, seen), WEEK, NOW)
    assert r is None or not r.is_new_research


@given(st.sampled_from([C.SOURCE_AGREEMENT, C.SINGLE_SOURCE]), offsets)
def test_unconfirmed_dates_are_never_promoted(_: C, offset: int) -> None:
    day = (NOW + timedelta(days=offset)).date().isoformat()
    secondary = c(JOURNAL, E.REPORTED_PUBLICATION_DATE, day, primary=False, source=S.OPENALEX)
    r = classify(work(secondary), WEEK, NOW)
    assert r is None or r.release_type is R.DATE_UNCERTAIN


def test_month_precision_primary_date_proves_an_old_paper_newly_indexed() -> None:
    """CVPR 2016 shape: Crossref knows only 2016-06; first seen in the window."""
    issued = c(CONFERENCE, E.ISSUED, "2016-06-01", upstream=U.CROSSREF, precision=P.MONTH)
    seen = c(
        CONFERENCE,
        E.FIRST_SEEN_BY_RESEARCHPILOT,
        "2026-11-11T08:00:00+00:00",
        primary=False,
        source=S.RESEARCHPILOT,
    )
    r = classify(work(issued, seen), WEEK, NOW)
    assert r is not None and (r.release_type, r.confidence) == (R.NEWLY_INDEXED_OLDER, C.UNCERTAIN)
