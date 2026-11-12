"""Runs both B0 benchmark splits end to end through the production code paths, from
recorded responses only (no network), and holds the hard gates.

B0 has AI-proposed labels: passing here means the rules behave as the development cases
expect. It is not a release estimate (EVALUATION_FRAMEWORK §2a).
"""

from __future__ import annotations

from pathlib import Path

from researchpilot.evaluation import gdates, gmatch
from researchpilot.evaluation.cases import load_dataset
from researchpilot.evaluation.harness import bench

BENCHMARKS = Path(__file__).resolve().parents[2] / "benchmarks"


def _url(libpq: str) -> str:
    return libpq.replace("postgresql://", "postgresql+psycopg://", 1)


def _roots(path: Path, recordings: list[str]) -> list[Path]:
    return [(path.parent / r).resolve() for r in recordings]


async def test_g_match_b0_hard_gates(migrated_db: str) -> None:
    path = BENCHMARKS / "g_match" / "b0.json"
    dataset = load_dataset(path)
    async with bench(_url(migrated_db), _roots(path, dataset.recordings)) as b:
        results, m = await gmatch.run(b, dataset)
        requests = list(b.transport.requests)
    assert m["not_evaluable"] == []  # every request was answered from a recording
    assert m["false_positive_merges"] == [] and m["adversarial_merges"] == []
    assert m["ambiguous_merged"] == [] and m["order_dependent"] == []
    assert m["reversible"] == 1.0 and m["rejection_sticky"] == 1.0
    assert m["related_not_same_detected"] == 1.0
    # Regression floor: B0 is fully correct today; any change must be explained.
    assert [r.case_id for r in results if not r.correct] == []
    assert requests  # the cases really went through the source clients


async def test_g_latest_dates_b0_hard_gates(migrated_db: str) -> None:
    path = BENCHMARKS / "g_latest_dates" / "b0.json"
    dataset = load_dataset(path)
    async with bench(_url(migrated_db), _roots(path, dataset.recordings)) as b:
        results, m = await gdates.run(b, dataset)
    assert m["not_evaluable"] == []
    assert m["incorrectly_verified"] == []
    assert m["uncertain_shown_as_confirmed"] == []
    assert m["journal_date_over_preprint"] == []
    assert m["revision_shown_as_new_work"] == []
    assert [r.case_id for r in results if not r.correct] == []
