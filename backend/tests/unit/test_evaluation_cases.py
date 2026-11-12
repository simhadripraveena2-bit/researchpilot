"""Benchmark protocol rules (EVALUATION_FRAMEWORK §2a-2b) and metric definitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from researchpilot.evaluation import gdates, gmatch
from researchpilot.evaluation.cases import (
    CUSTODIAN_ENV,
    REPO_ROOT,
    Dataset,
    SplitViolation,
    guard_split,
    load_dataset,
    overlapping_works,
)
from researchpilot.evaluation.report import build

BENCHMARKS = Path(__file__).resolve().parents[2] / "benchmarks"


def _match_case(case_id: str, status: str = "ai_proposed", **over: Any) -> dict[str, Any]:
    case = {
        "id": case_id,
        "category": "similar_title_different",
        "adversarial": True,
        "a": "10.1000/a",
        "b": "10.1000/b",
        "expected": {
            "relationship": "different",
            "outcome": "no_match",
            "auto_merge_allowed": False,
            "user_confirmation_required": False,
            "decisive_evidence": False,
        },
        "explanation": "x",
        "evidence": [],
        "provenance": "recorded",
        "labels": {"status": status, "guideline": "g", "proposed_by": "p"},
    }
    case.update(over)
    return case


def _dataset(split: str, cases: list[dict[str, Any]]) -> Dataset:
    return Dataset.model_validate(
        {
            "benchmark": "G-MATCH",
            "split": split,
            "version": "t",
            "description": "t",
            "recordings": [],
            "match_cases": cases,
        }
    )


def test_case_id_must_match_split(tmp_path: Path) -> None:
    with pytest.raises(SplitViolation, match="not a B0 case id"):
        guard_split(_dataset("B0", [_match_case("GM-B1-001")]), tmp_path / "d.json")


def test_b1_refuses_labels_that_are_not_expert_adjudicated(tmp_path: Path) -> None:
    for status in ("ai_proposed", "team_reviewed"):
        with pytest.raises(SplitViolation, match="expert-adjudicated"):
            guard_split(_dataset("B1", [_match_case("GM-B1-001", status)]), tmp_path / "d")


def test_synthetic_cases_are_development_only(tmp_path: Path) -> None:
    case = _match_case("GM-B2-001", "expert_adjudicated", provenance="synthetic")
    with pytest.raises(SplitViolation, match="synthetic"):
        guard_split(_dataset("B2", [case]), tmp_path / "d")


def test_b3_is_refused_inside_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CUSTODIAN_ENV, "1")
    data = _dataset("B3", [_match_case("GM-B3-001", "expert_adjudicated")])
    with pytest.raises(SplitViolation, match="must not be stored in the repository"):
        guard_split(data, REPO_ROOT / "backend" / "benchmarks" / "b3.json")


def test_b3_is_refused_without_the_custodian(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(CUSTODIAN_ENV, raising=False)
    data = _dataset("B3", [_match_case("GM-B3-001", "expert_adjudicated")])
    outside = Path("/") / "custodian-storage" / "b3.json"
    assert not outside.is_relative_to(REPO_ROOT)
    with pytest.raises(SplitViolation, match="custodian"):
        guard_split(data, outside)
    monkeypatch.setenv(CUSTODIAN_ENV, "1")
    guard_split(data, outside)  # the custodian, outside the repository: allowed


def test_duplicate_ids_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    data = _dataset("B0", [_match_case("GM-B0-001"), _match_case("GM-B0-001")])
    path.write_text(json.dumps(data.model_dump(mode="json")))
    with pytest.raises(SplitViolation, match="duplicate"):
        load_dataset(path)


def test_identifiers_must_be_supported() -> None:
    with pytest.raises(ValidationError, match="unsupported identifier"):
        _dataset("B0", [_match_case("GM-B0-001", a="not an identifier")])


def test_overlap_is_found_by_hashed_work() -> None:
    b0 = _dataset("B0", [_match_case("GM-B0-001")])
    b1 = _dataset(
        "B1", [_match_case("GM-B1-001", "expert_adjudicated", a="10.1000/A", b="10.1000/z")]
    )
    assert overlapping_works([b0, b1]) == {("B0", "B1"): 1}  # case-insensitive
    b1b = _dataset(
        "B1", [_match_case("GM-B1-001", "expert_adjudicated", a="10.1000/z", b="10.1000/y")]
    )
    assert overlapping_works([b0, b1b]) == {}


def test_committed_b0_datasets_load_and_do_not_overlap() -> None:
    match = load_dataset(BENCHMARKS / "g_match" / "b0.json")
    dates = load_dataset(BENCHMARKS / "g_latest_dates" / "b0.json")
    assert match.split.value == dates.split.value == "B0"
    for d in (match, dates):
        cases = d.match_cases or d.date_cases
        assert all(c.labels.status.value == "ai_proposed" for c in cases)  # stated honestly
        assert all(c.provenance.value == "recorded" for c in cases)
    assert not list(BENCHMARKS.rglob("b3*.json"))  # B3 is never in the repository


# --- metric definitions --------------------------------------------------------------------


def _mr(case_id: str, expected: str, rel: str, observed: str, merged: bool, **kw: Any) -> Any:
    obs = gmatch.MatchObservation(observed, None, merged)
    r = gmatch.MatchCaseResult(
        case_id=case_id,
        category=kw.pop("category", "c"),
        adversarial=kw.pop("adversarial", False),
        expected_outcome=expected,
        expected_relationship=rel,
        decisive_evidence=kw.pop("decisive", False),
        observed=obs,
        reversed_order=obs,
        **kw,
    )
    r.correct = observed == expected
    return r


def test_gmatch_metrics_count_false_positive_merges_and_ambiguity() -> None:
    results = [
        _mr(
            "1",
            "auto_match",
            "same_work",
            "auto_match",
            True,
            decisive=True,
            reversible=True,
            rejection_sticky=True,
        ),
        _mr(
            "2",
            "no_match",
            "different",
            "auto_match",
            True,
            adversarial=True,
            reversible=True,
            rejection_sticky=True,
        ),
        _mr(
            "3",
            "possible_match",
            "same_work",
            "auto_match",
            True,
            reversible=True,
            rejection_sticky=False,
        ),
        _mr("4", "auto_match", "same_work", "possible_match", False, decisive=True),
        _mr("5", "related_not_same", "related_not_same", "related_not_same", False),
    ]
    m = gmatch.metrics(results)
    assert m["false_positive_merges"] == ["2"]
    assert m["adversarial_merges"] == ["2"]
    assert m["auto_merge_precision"] == round(2 / 3, 4)
    assert m["recall_decisive"] == 0.5
    assert m["false_negatives"] == ["4"]
    assert m["ambiguous_merged"] == ["3"] and m["ambiguous_kept_possible"] == 0.0
    assert m["related_not_same_detected"] == 1.0
    assert m["rejection_sticky"] == round(2 / 3, 4)


def test_gmatch_errors_are_not_scored() -> None:
    bad = gmatch.MatchCaseResult(
        "9", "c", False, "no_match", "different", False, error="not evaluable: x"
    )
    m = gmatch.metrics([bad])
    assert (m["scored"], m["not_evaluable"], m["accuracy"]) == (0, ["9"], None)


def test_gdates_incorrectly_verified_and_journal_over_preprint() -> None:
    def case(expected: dict[str, Any]) -> Any:
        from researchpilot.evaluation.cases import DateCase

        return DateCase.model_validate(
            {
                "id": "GD-B0-001",
                "category": "journal_of_older_preprint",
                "identifiers": ["10.1000/a"],
                "expected": expected,
                "explanation": "x",
                "evidence": [],
                "provenance": "recorded",
                "labels": {"status": "ai_proposed", "guideline": "g", "proposed_by": "p"},
            }
        )

    c = case(
        {
            "first_public_date": "2023-01-02",
            "basis": "posted",
            "confidence": "verified",
            "first_public_kind": "preprint",
        }
    )
    r = gdates.DateCaseResult("GD-B0-001", c.category, c.expected.model_dump(mode="json"))
    r.observed = gdates.DateObservation(
        "2024-06-03", "published_online", "verified", "published", None, None, True
    )
    gdates._score(r, c)
    assert r.incorrectly_verified and r.journal_date_over_preprint and not r.correct
    m = gdates.metrics([r])
    assert m["incorrectly_verified"] == ["GD-B0-001"]
    assert m["journal_date_over_preprint"] == ["GD-B0-001"]

    u = case({"first_public_date": None, "basis": None, "confidence": "uncertain"})
    r2 = gdates.DateCaseResult("GD-B0-001", u.category, u.expected.model_dump(mode="json"))
    r2.observed = gdates.DateObservation(None, None, "uncertain", None, None, None, True)
    gdates._score(r2, u)
    assert r2.correct and not r2.incorrectly_verified


def test_b3_report_is_aggregate_only(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _dataset("B3", [_match_case("GM-B3-001", "expert_adjudicated")])
    r = _mr(
        "GM-B3-001",
        "no_match",
        "different",
        "auto_match",
        True,
        adversarial=True,
        reversible=True,
        rejection_sticky=True,
    )
    m = gmatch.metrics([r])
    md, payload = build(data, gmatch.as_dicts([r]), m)
    assert "GM-B3-001" not in md and "10.1000" not in md
    assert payload["results"] == [] and payload["metrics"]["false_positive_merges"] == 1
    assert "Gates FAIL on B3" in payload["verdict"]


def test_b0_report_never_claims_release_readiness() -> None:
    data = _dataset("B0", [_match_case("GM-B0-001")])
    r = _mr("GM-B0-001", "no_match", "different", "no_match", False)
    _, payload = build(data, gmatch.as_dicts([r]), gmatch.metrics([r]))
    assert payload["verdict"].startswith("NOT a release decision")
