"""G-MATCH: does the Version Matcher keep the same work together and everything else apart?

Every pair runs in both orders (the result must not depend on which record came first).
Where the matcher merged, the merge is split again by a user (as the API does) to check
reversibility and that the rejection sticks: re-matching both works must not merge them.

Metrics (EVALUATION_FRAMEWORK §3.1): auto-merge precision; recall for pairs with decisive
links and for pairs without; **false-positive merges** (the most serious failure; adversarial
ones separately); false negatives; ambiguous pairs kept as possible matches; related-not-same
detection; order dependence; reversibility.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

import sqlalchemy as sa

from researchpilot.db.session import session_scope
from researchpilot.domain.enums import MatchOutcome
from researchpilot.evaluation.cases import Dataset, MatchCase
from researchpilot.evaluation.harness import Bench
from researchpilot.services.matching.store import match_work, split


@dataclass
class MatchObservation:
    outcome: str  # auto_match (merged) | possible_match | related_not_same | no_match
    relation: str | None
    merged: bool


@dataclass
class MatchCaseResult:
    case_id: str
    category: str
    adversarial: bool
    expected_outcome: str
    expected_relationship: str
    decisive_evidence: bool
    observed: MatchObservation | None = None
    reversed_order: MatchObservation | None = None
    order_dependent: bool = False
    correct: bool = False
    reversible: bool | None = None  # None: nothing was merged
    rejection_sticky: bool | None = None
    error: str | None = None
    aggregators_answered: list[str] = field(default_factory=list)
    aggregators_unrecorded: list[str] = field(default_factory=list)


async def _observe(bench: Bench, first: str, second: str) -> MatchObservation:
    project = await bench.reset()
    pa = await bench.add(project, first)
    pb = await bench.add(project, second)
    wa, wb = await bench.active(pa), await bench.active(pb)
    if wa == wb:
        return MatchObservation(MatchOutcome.AUTO_MATCH.value, None, True)
    async with session_scope(bench.sessions) as session:
        row = (
            await session.execute(
                sa.text(
                    "SELECT outcome, relation FROM paper_match_decisions WHERE "
                    "(paper_a = :a AND paper_b = :b) OR (paper_a = :b AND paper_b = :a)"
                ),
                {"a": wa, "b": wb},
            )
        ).first()
    if row is None:  # never a candidate pair: nothing links them
        return MatchObservation(MatchOutcome.NO_MATCH.value, None, False)
    return MatchObservation(str(row.outcome), str(row.relation), False)


async def _snapshot(bench: Bench, manifestations: list[uuid.UUID]) -> dict[str, Any]:
    async with session_scope(bench.sessions) as session:
        rows = await session.execute(
            sa.text(
                "SELECT m.id, m.paper_id, "
                "(SELECT count(*) FROM paper_dates d WHERE d.manifestation_id = m.id) AS dates, "
                "(SELECT count(*) FROM paper_identifiers i WHERE i.manifestation_id = m.id) "
                "AS ids, (SELECT count(*) FROM paper_source_links s "
                "WHERE s.manifestation_id = m.id) AS links "
                "FROM paper_manifestations m WHERE m.id = ANY(:m) ORDER BY m.id"
            ),
            {"m": manifestations},
        )
        return {str(r.id): (str(r.paper_id), r.dates, r.ids, r.links) for r in rows}


async def _check_reversal(bench: Bench, case: MatchCase) -> tuple[bool, bool]:
    """Re-run the pair, split the merge that joined it as a user would, and check the result.

    Reversible: every manifestation the merge moved is back on the merged work, the others stay
    on the survivor, and no manifestation lost or gained dates, identifiers or source records.
    Sticky: re-matching both works and re-adding both identifiers must not merge them again.
    (A merge can happen inside the first ``add`` when a record's own link pulls in the other
    version, so the event, not the add order, says which work was merged into which.)
    """
    project = await bench.reset()
    await bench.add(project, case.a)
    await bench.add(project, case.b)
    async with session_scope(bench.sessions) as session:
        event = (
            await session.execute(
                sa.text(
                    "SELECT id, surviving_id, merged_id, moved FROM paper_merge_events "
                    "WHERE reverted_at IS NULL ORDER BY created_at DESC, id DESC LIMIT 1"
                )
            )
        ).first()
    if event is None:
        return False, False
    moved = set(event.moved["manifestations"])
    before = await _snapshot_all(bench)
    async with session_scope(bench.sessions) as session:
        await split(session, event.id, by_user=True)
    after = await _snapshot_all(bench)
    survivor, merged = str(event.surviving_id), str(event.merged_id)
    reversible = set(before) == set(after) and all(
        after[m][0] == (merged if m in moved else survivor) and after[m][1:] == before[m][1:]
        for m in before
        if before[m][0] == survivor
    )
    async with session_scope(bench.sessions) as session:
        reversible = reversible and (
            await session.scalar(
                sa.text("SELECT merged_into_id IS NULL FROM papers WHERE id = :m"),
                {"m": event.merged_id},
            )
        )
        await match_work(session, event.surviving_id)
        await match_work(session, event.merged_id)
    await bench.add(project, case.a)
    await bench.add(project, case.b)
    sticky = await bench.active(event.surviving_id) != await bench.active(event.merged_id)
    return bool(reversible), sticky


async def _snapshot_all(bench: Bench) -> dict[str, Any]:
    async with session_scope(bench.sessions) as session:
        ids = list(
            (await session.execute(sa.text("SELECT id FROM paper_manifestations"))).scalars()
        )
    return await _snapshot(bench, ids)


async def run_case(bench: Bench, case: MatchCase) -> MatchCaseResult:
    result = MatchCaseResult(
        case_id=case.id,
        category=case.category,
        adversarial=case.adversarial,
        expected_outcome=case.expected.outcome.value,
        expected_relationship=case.expected.relationship,
        decisive_evidence=case.expected.decisive_evidence,
    )
    try:
        result.observed = await _observe(bench, case.a, case.b)
        trace_a = bench.transport.trace
        result.reversed_order = await _observe(bench, case.b, case.a)
        trace_b = bench.transport.trace
        missing = trace_a.missing + trace_b.missing
        if missing:
            result.error = f"not evaluable: unrecorded request {missing[0]}"
            return result
        result.aggregators_answered = sorted(
            trace_a.aggregators_answered | trace_b.aggregators_answered
        )
        result.aggregators_unrecorded = sorted(
            trace_a.aggregators_unrecorded | trace_b.aggregators_unrecorded
        )
        result.order_dependent = (result.observed.outcome, result.observed.merged) != (
            result.reversed_order.outcome,
            result.reversed_order.merged,
        )
        result.correct = (
            not result.order_dependent and result.observed.outcome == result.expected_outcome
        )
        if result.observed.merged or result.reversed_order.merged:
            result.reversible, result.rejection_sticky = await _check_reversal(bench, case)
    except Exception as exc:  # a crash is a harness error, never a score
        result.error = f"{type(exc).__name__}: {exc}"[:500]
    return result


def _ratio(n: int, d: int) -> float | None:
    return None if d == 0 else round(n / d, 4)


def metrics(results: list[MatchCaseResult]) -> dict[str, Any]:
    scored = [r for r in results if r.error is None and r.observed is not None]
    merged = [
        r
        for r in scored
        if r.observed and (r.observed.merged or (r.reversed_order and r.reversed_order.merged))
    ]
    same = [r for r in scored if r.expected_relationship == "same_work"]
    fp = [r for r in merged if r.expected_relationship != "same_work"]
    expected_auto = [r for r in scored if r.expected_outcome == MatchOutcome.AUTO_MATCH.value]
    decisive_same = [r for r in same if r.decisive_evidence]
    nolink_same = [r for r in same if not r.decisive_evidence]
    ambiguous = [r for r in scored if r.expected_outcome == MatchOutcome.POSSIBLE_MATCH.value]
    related = [r for r in scored if r.expected_relationship == "related_not_same"]

    def ok_merge(r: MatchCaseResult) -> bool:
        return bool(r.observed and r.observed.merged and not r.order_dependent)

    confusion: Counter[str] = Counter(
        f"{r.expected_outcome} -> {r.observed.outcome if r.observed else 'error'}" for r in scored
    )
    return {
        "cases": len(results),
        "scored": len(scored),
        "not_evaluable": [r.case_id for r in results if r.error],
        "accuracy": _ratio(sum(r.correct for r in scored), len(scored)),
        "auto_merge_precision": _ratio(len(merged) - len(fp), len(merged)),
        "false_positive_merges": [r.case_id for r in fp],
        "adversarial_merges": [r.case_id for r in fp if r.adversarial],
        "recall_decisive": _ratio(sum(ok_merge(r) for r in decisive_same), len(decisive_same)),
        "recall_without_decisive_link_merged_or_possible": _ratio(
            sum(
                1
                for r in nolink_same
                if r.observed
                and (r.observed.merged or r.observed.outcome == MatchOutcome.POSSIBLE_MATCH.value)
            ),
            len(nolink_same),
        ),
        "false_negatives": [r.case_id for r in expected_auto if not ok_merge(r)],
        "ambiguous_kept_possible": _ratio(
            sum(
                1
                for r in ambiguous
                if r.observed
                and not r.observed.merged
                and r.observed.outcome == MatchOutcome.POSSIBLE_MATCH.value
            ),
            len(ambiguous),
        ),
        "ambiguous_merged": [r.case_id for r in ambiguous if r.observed and r.observed.merged],
        "related_not_same_detected": _ratio(
            sum(1 for r in related if r.observed and r.observed.outcome == r.expected_outcome),
            len(related),
        ),
        "order_dependent": [r.case_id for r in scored if r.order_dependent],
        "reversible": _ratio(sum(1 for r in merged if r.reversible), len(merged)),
        "rejection_sticky": _ratio(sum(1 for r in merged if r.rejection_sticky), len(merged)),
        "confusion": dict(sorted(confusion.items())),
        "by_category": {
            cat: {
                "cases": sum(1 for r in scored if r.category == cat),
                "correct": sum(1 for r in scored if r.category == cat and r.correct),
            }
            for cat in sorted({r.category for r in scored})
        },
    }


async def run(bench: Bench, dataset: Dataset) -> tuple[list[MatchCaseResult], dict[str, Any]]:
    results = [await run_case(bench, case) for case in dataset.match_cases]
    return results, metrics(results)


def as_dicts(results: list[MatchCaseResult]) -> list[dict[str, Any]]:
    return [asdict(r) for r in results]
