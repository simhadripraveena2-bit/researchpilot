"""G-LATEST-DATES: is a work's first public appearance found, with the right confidence?

Each case ingests one work (one or more versions) from recorded responses, optionally
captures the recorded arXiv announcement feed, and reads what the Date Resolver concluded:
first public date and basis, confidence, the manifestation it came from, the unconfirmed
candidate date, and (when the case gives a window) the release type.

Metrics: first-public-date accuracy; **incorrectly verified dates** (verified/corroborated
when the case says otherwise, or a wrong verified date: the most serious failure);
uncertain-class accuracy; conflict handling; preprint-vs-journal distinction (a journal date
must never be first when an earlier preprint exists); revision-vs-new-work distinction.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from researchpilot.db.session import session_scope
from researchpilot.domain.enums import DateConfidence, ReleaseType
from researchpilot.domain.windows import from_dates
from researchpilot.evaluation.cases import Dataset, DateCase
from researchpilot.evaluation.harness import Bench
from researchpilot.services.dates.announcements import capture
from researchpilot.services.dates.release_types import classify
from researchpilot.services.dates.releases import load_work_dates

CONFIRMED = frozenset({DateConfidence.VERIFIED.value, DateConfidence.CORROBORATED.value})
UNCERTAIN_CLASS = frozenset(
    {
        DateConfidence.SINGLE_SOURCE.value,
        DateConfidence.SOURCE_AGREEMENT.value,
        DateConfidence.CONFLICTING.value,
        DateConfidence.UNCERTAIN.value,
    }
)


@dataclass
class DateObservation:
    first_public_date: str | None
    basis: str | None
    confidence: str
    first_public_kind: str | None
    candidate_public_date: str | None
    release_type: str | None  # "none" when nothing placed the work in the window
    one_work: bool  # all identifiers ended in one work


@dataclass
class DateCaseResult:
    case_id: str
    category: str
    expected: dict[str, Any]
    observed: DateObservation | None = None
    date_correct: bool = False
    confidence_correct: bool = False
    release_correct: bool | None = None
    incorrectly_verified: bool = False
    journal_date_over_preprint: bool = False
    correct: bool = False
    error: str | None = None
    aggregators_answered: list[str] = field(default_factory=list)
    aggregators_unrecorded: list[str] = field(default_factory=list)


async def _observe(bench: Bench, case: DateCase) -> DateObservation:
    project = await bench.reset()
    works = [await bench.add(project, identifier) for identifier in case.identifiers]
    if case.capture_feeds:
        await capture(bench.sessions, bench.sources.arxiv_feed, list(case.capture_feeds))
    actives = {await bench.active(w) for w in works}
    work = await bench.active(works[0])
    async with session_scope(bench.sessions) as session:
        row = (
            await session.execute(
                sa.text(
                    "SELECT p.first_public_appearance, p.first_public_basis, p.date_confidence, "
                    "p.candidate_public_date, m.kind FROM papers p LEFT JOIN "
                    "paper_manifestations m ON m.id = p.first_public_manifestation_id "
                    "WHERE p.id = :p"
                ),
                {"p": work},
            )
        ).one()
        release: str | None = None
        expected = case.expected
        if expected.window is not None:
            today = datetime.now(UTC).date()
            first, last = (today, today) if expected.window == "run_day" else expected.window
            placed = classify(
                await load_work_dates(session, work), from_dates(first, last), datetime.now(UTC)
            )
            release = placed.release_type.value if placed else "none"
    return DateObservation(
        first_public_date=row.first_public_appearance.date().isoformat()
        if row.first_public_appearance
        else None,
        basis=row.first_public_basis,
        confidence=str(row.date_confidence),
        first_public_kind=row.kind,
        candidate_public_date=row.candidate_public_date.isoformat()
        if row.candidate_public_date
        else None,
        release_type=release,
        one_work=len(actives) == 1,
    )


def _score(result: DateCaseResult, case: DateCase) -> None:
    o, e = result.observed, case.expected
    assert o is not None
    want_date = e.first_public_date.isoformat() if e.first_public_date else None
    want_basis = e.basis.value if e.basis else None
    result.date_correct = o.first_public_date == want_date and o.basis == want_basis
    result.confidence_correct = o.confidence == e.confidence.value
    if e.release_type is not None:
        result.release_correct = o.release_type == (
            e.release_type if isinstance(e.release_type, str) else e.release_type.value
        )
    confirmed = o.confidence in CONFIRMED
    result.incorrectly_verified = confirmed and (
        e.confidence.value not in CONFIRMED or not result.date_correct
    )
    result.journal_date_over_preprint = (
        e.first_public_kind == "preprint" and o.first_public_kind not in (None, "preprint")
    )
    if e.candidate_public_date is not None:
        candidate_ok = o.candidate_public_date == e.candidate_public_date.isoformat()
    else:
        candidate_ok = True
    kind_ok = e.first_public_kind is None or o.first_public_kind == e.first_public_kind
    result.correct = (
        result.date_correct
        and result.confidence_correct
        and kind_ok
        and candidate_ok
        and result.release_correct is not False
        and o.one_work
    )


async def run_case(bench: Bench, case: DateCase) -> DateCaseResult:
    result = DateCaseResult(
        case_id=case.id, category=case.category, expected=case.expected.model_dump(mode="json")
    )
    try:
        result.observed = await _observe(bench, case)
        trace = bench.transport.trace
        if trace.missing:
            result.error = f"not evaluable: unrecorded request {trace.missing[0]}"
            return result
        result.aggregators_answered = sorted(trace.aggregators_answered)
        result.aggregators_unrecorded = sorted(trace.aggregators_unrecorded)
        _score(result, case)
    except Exception as exc:  # a crash is a harness error, never a score
        result.error = f"{type(exc).__name__}: {exc}"[:500]
    return result


def _ratio(n: int, d: int) -> float | None:
    return None if d == 0 else round(n / d, 4)


def metrics(results: list[DateCaseResult]) -> dict[str, Any]:
    scored = [r for r in results if r.error is None and r.observed is not None]

    def by(categories: set[str]) -> list[DateCaseResult]:
        return [r for r in scored if r.category in categories]

    expected_uncertain = [r for r in scored if r.expected["confidence"] in UNCERTAIN_CLASS]
    with_release = [r for r in scored if r.release_correct is not None]
    confusion: Counter[str] = Counter(
        f"{r.expected['confidence']} -> {r.observed.confidence if r.observed else 'error'}"
        for r in scored
    )
    revisions = by({"arxiv_revision"})
    return {
        "cases": len(results),
        "scored": len(scored),
        "not_evaluable": [r.case_id for r in results if r.error],
        "accuracy": _ratio(sum(r.correct for r in scored), len(scored)),
        "first_public_date_accuracy": _ratio(sum(r.date_correct for r in scored), len(scored)),
        "confidence_accuracy": _ratio(sum(r.confidence_correct for r in scored), len(scored)),
        "incorrectly_verified": [r.case_id for r in scored if r.incorrectly_verified],
        "uncertain_class_accuracy": _ratio(
            sum(
                1
                for r in expected_uncertain
                if r.observed and r.observed.confidence == r.expected["confidence"]
            ),
            len(expected_uncertain),
        ),
        "uncertain_shown_as_confirmed": [
            r.case_id
            for r in expected_uncertain
            if r.observed and r.observed.confidence in CONFIRMED
        ],
        "conflicts_detected": _ratio(
            sum(1 for r in by({"conflicting"}) if r.confidence_correct),
            len(by({"conflicting"})),
        ),
        "journal_date_over_preprint": [r.case_id for r in scored if r.journal_date_over_preprint],
        "revision_shown_as_new_work": [
            r.case_id
            for r in revisions
            if r.observed
            and r.observed.release_type
            in (
                ReleaseType.NEW_PREPRINT.value,
                ReleaseType.NEW_PUBLICATION.value,
            )
        ],
        "release_type_accuracy": _ratio(
            sum(1 for r in with_release if r.release_correct), len(with_release)
        ),
        "confusion": dict(sorted(confusion.items())),
        "by_category": {
            cat: {
                "cases": sum(1 for r in scored if r.category == cat),
                "correct": sum(1 for r in scored if r.category == cat and r.correct),
            }
            for cat in sorted({r.category for r in scored})
        },
    }


async def run(bench: Bench, dataset: Dataset) -> tuple[list[DateCaseResult], dict[str, Any]]:
    results = [await run_case(bench, case) for case in dataset.date_cases]
    return results, metrics(results)


def as_dicts(results: list[DateCaseResult]) -> list[dict[str, Any]]:
    return [asdict(r) for r in results]
