"""Two-stage blind B0 review (scripts/b0_review_sheets.py).

Stage 1 must not expose AI labels or expected behaviour; Stage 2 reveals them only for cases
whose Stage 1 answer is submitted, and locks that answer; regeneration never touches reviewer
files. Answers used here are synthetic test fixtures written to a temporary directory; the
committed answer files stay blank.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parents[2]
FIXTURE_REVIEWER = "test-fixture-not-a-human-decision"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "b0_review_sheets", BACKEND / "scripts" / "b0_review_sheets.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


M = _module()


def _cases(benchmark: str) -> list[dict[str, Any]]:
    data = json.loads(M.DATASETS[benchmark].read_text())
    return list(data.get("match_cases") or data.get("date_cases"))


def _sections(text: str) -> dict[str, str]:
    parts = re.split(r"^## ", text, flags=re.M)[1:]
    return {p.split("\n", 1)[0].strip(): p for p in parts}


def _without_records(section: str) -> str:
    """The section minus the verbatim source-record summaries (titles of real papers may
    contain words such as 'different' or 'uncertain')."""
    kept, inside = [], False
    for line in section.splitlines():
        if line.startswith("- **Original source records"):
            inside = True
            continue
        if inside and line.startswith("- **"):
            inside = False
        if not inside:
            kept.append(line)
    return "\n".join(kept)


def _stem(benchmark: str) -> str:
    return benchmark.lower().replace("-", "_")


def _paths(out: Path, benchmark: str) -> dict[str, Path]:
    stem = _stem(benchmark)
    return {
        "s1": out / "stage1" / f"{stem}_b0_stage1.csv",
        "s2": out / "stage2" / f"{stem}_b0_stage2.csv",
        "s1md": out / "stage1" / f"{stem.upper()}_B0_STAGE1.md",
        "s2md": out / "stage2" / f"{stem.upper()}_B0_STAGE2.md",
    }


def _set_row(path: Path, case_id: str, **values: str) -> None:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = list(reader)
    for row in rows:
        if row["case_id"] == case_id:
            row.update(values)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


MATCH_ANSWER = {
    "reviewer": FIXTURE_REVIEWER,
    "true_relationship": "same_work",
    "relationship_detail": "preprint_and_published",
    "evidence_urls": "https://example.org/fixture",
    "submitted_at": "2026-11-13",
}
DATE_ANSWER = {
    "reviewer": FIXTURE_REVIEWER,
    "determinable": "not_determinable",
    "evidence_urls": "https://example.org/fixture",
    "submitted_at": "2026-11-13",
}


@pytest.fixture
def out(tmp_path: Path) -> Path:
    M.write(M.build(tmp_path))
    return tmp_path


# --- Stage 1 exposes nothing of the AI label ------------------------------------------------

HIDDEN_TOKENS = [
    "auto_match",
    "possible_match",
    "no_match",
    "decisive",
    "adversarial",
    "verified",
    "corroborated",
    "source_agreement",
    "single_source",
    "conflicting",
    "uncertain",
    "submission_only",
    "new_preprint",
    "new_publication",
    "revised_version",
    "newly_indexed_older",
    "published_version_of_preprint",
    "correction_notice",
    "date_uncertain",
    "ai_proposed",
    "AI-proposed",
    "Expected system behaviour",
    "TRUTH vs POLICY",
]


@pytest.mark.parametrize("benchmark", ["G-MATCH", "G-LATEST-DATES"])
def test_stage1_does_not_expose_ai_labels_or_expected_outcomes(benchmark: str) -> None:
    text = (M.OUT / "stage1" / f"{_stem(benchmark).upper()}_B0_STAGE1.md").read_text()
    sections = _sections(text)
    cases = _cases(benchmark)
    assert set(sections) == {c["id"] for c in cases}  # every case, IDs preserved
    categories = {c["category"] for c in cases}
    for case in cases:
        section = sections[case["id"]]
        assert case["explanation"] not in section
        for item in case["evidence"]:  # AI-written evidence lines
            assert item not in section, (case["id"], item)
        for note in M.NOTES.get(case["id"], []):
            assert note not in section
        for category in categories:
            assert category not in section, (case["id"], category)
        for token in HIDDEN_TOKENS:  # also inside records for the label-only tokens
            assert token not in _without_records(section), (case["id"], token)
        if benchmark == "G-MATCH":
            assert case["expected"]["relationship"] not in _without_records(section)
        assert "backend/benchmarks/g_" not in section  # no dataset path
        assert "reports" not in section  # no benchmark results
    # Order is shuffled: consecutive IDs (same category) are not presented in ID order.
    assert list(sections) != sorted(sections)


@pytest.mark.parametrize("benchmark", ["G-MATCH", "G-LATEST-DATES"])
def test_stage1_keeps_source_provenance(benchmark: str) -> None:
    sections = _sections(
        (M.OUT / "stage1" / f"{_stem(benchmark).upper()}_B0_STAGE1.md").read_text()
    )
    for case in _cases(benchmark):
        section = sections[case["id"]]
        ids = [case["a"], case["b"]] if benchmark == "G-MATCH" else case["identifiers"]
        for identifier in ids:
            assert f"`{identifier}`" in section
        assert "Primary sources to check" in section
        assert "Original source records" in section
        assert re.search(r"`backend/(benchmarks/recordings|tests/fixtures/sources)/", section)


def test_stage1_answer_files_carry_no_labels() -> None:
    for benchmark in M.DATASETS:
        paths = _paths(M.OUT, benchmark)
        for key in ("s1", "s2"):
            with paths[key].open(newline="") as handle:
                reader = csv.DictReader(handle)
                assert not any(
                    "label" in f and "corrected" not in f for f in reader.fieldnames or []
                )
                assert {r["case_id"] for r in reader} == {c["id"] for c in _cases(benchmark)}


def test_generated_answer_files_fill_no_reviewer_field(tmp_path: Path) -> None:
    files = M.build(tmp_path)
    for path, text in files.items():
        if path.suffix == ".csv":
            for row in csv.DictReader(text.splitlines()):
                assert all(not v for k, v in row.items() if k != "case_id"), path


# --- Stage 2 reveals only after Stage 1, and locks Stage 1 -----------------------------------


def test_stage2_reveals_nothing_before_stage1(out: Path) -> None:
    for benchmark in M.DATASETS:
        text = _paths(out, benchmark)["s2md"].read_text()
        for case in _cases(benchmark):
            assert case["explanation"] not in text
        assert text.count("Locked: Stage 1 not submitted.") == len(_cases(benchmark))
    assert json.loads((out / "stage1_locks.json").read_text()) == {}


def test_stage2_reveals_a_case_only_after_its_stage1_is_submitted(out: Path) -> None:
    match = _cases("G-MATCH")
    first, other = match[0], match[1]
    paths = _paths(out, "G-MATCH")
    # Filled in but not submitted: still hidden.
    _set_row(paths["s1"], first["id"], **{**MATCH_ANSWER, "submitted_at": ""})
    M.write(M.build(out))
    hidden = _sections(paths["s2md"].read_text())[first["id"]]
    assert first["explanation"] not in hidden and "Locked" in hidden
    # Submitted: revealed (label, expected behaviour, explanation), and locked.
    _set_row(paths["s1"], first["id"], **MATCH_ANSWER)
    M.write(M.build(out))
    sections = _sections(paths["s2md"].read_text())
    assert first["explanation"] in sections[first["id"]]
    assert f"outcome `{first['expected']['outcome']}`" in sections[first["id"]]
    assert "Your Stage 1 ground truth (locked):** `same_work`" in sections[first["id"]]
    assert sections[other["id"]].count("Locked: Stage 1 not submitted.") == 1
    assert other["explanation"] not in sections[other["id"]]
    assert first["id"] in json.loads((out / "stage1_locks.json").read_text())

    dates = _cases("G-LATEST-DATES")
    dpaths = _paths(out, "G-LATEST-DATES")
    _set_row(dpaths["s1"], dates[0]["id"], **DATE_ANSWER)
    M.write(M.build(out))
    dsections = _sections(dpaths["s2md"].read_text())
    assert dates[0]["explanation"] in dsections[dates[0]["id"]]
    assert "Your Stage 1 ground truth (locked):** not determinable" in dsections[dates[0]["id"]]


def test_incomplete_submitted_stage1_is_refused(out: Path) -> None:
    case = _cases("G-LATEST-DATES")[0]
    paths = _paths(out, "G-LATEST-DATES")
    _set_row(paths["s1"], case["id"], **{**DATE_ANSWER, "determinable": "yes"})  # no date
    with pytest.raises(M.ReviewError, match="lacks"):
        M.build(out)
    _set_row(
        paths["s1"],
        case["id"],
        determinable="yes",
        true_first_public_date="13/11/2026",
        true_event="online_publication",
        true_manifestation="published",
    )
    with pytest.raises(M.ReviewError, match="YYYY-MM-DD"):
        M.build(out)
    _set_row(paths["s1"], case["id"], true_event="press_release")
    with pytest.raises(M.ReviewError, match="not in"):
        M.build(out)


def test_stage1_answer_cannot_change_after_reveal(out: Path) -> None:
    case = _cases("G-MATCH")[0]
    paths = _paths(out, "G-MATCH")
    _set_row(paths["s1"], case["id"], **MATCH_ANSWER)
    M.write(M.build(out))  # revealed and locked
    _set_row(paths["s1"], case["id"], true_relationship="different")
    with pytest.raises(M.ReviewError, match="changed after Stage 2 was revealed"):
        M.build(out)
    _set_row(paths["s1"], case["id"], true_relationship="same_work")  # restored
    M.build(out)


def test_stage2_answer_before_stage1_is_refused(out: Path) -> None:
    case = _cases("G-MATCH")[0]
    _set_row(
        _paths(out, "G-MATCH")["s2"], case["id"], reviewer=FIXTURE_REVIEWER, decision="confirm"
    )
    with pytest.raises(M.ReviewError, match="before Stage 1"):
        M.build(out)


# --- regeneration never touches reviewer decisions ------------------------------------------


def test_regeneration_preserves_reviewer_files(out: Path) -> None:
    case = _cases("G-MATCH")[0]
    paths = _paths(out, "G-MATCH")
    _set_row(paths["s1"], case["id"], **MATCH_ANSWER)
    M.write(M.build(out))
    _set_row(
        paths["s2"],
        case["id"],
        reviewer=FIXTURE_REVIEWER,
        decision="confirm",
        reason="fixture",
        evidence_urls="https://example.org/fixture",
        review_date="2026-11-13",
    )
    before = {p: p.read_bytes() for p in out.rglob("*.csv")}
    locks = (out / "stage1_locks.json").read_bytes()
    for _ in range(2):
        files = M.build(out)
        assert not any(p.suffix == ".csv" for p in files)  # existing answer files never rebuilt
        M.write(files)
    assert {p: p.read_bytes() for p in out.rglob("*.csv")} == before
    assert (out / "stage1_locks.json").read_bytes() == locks
    assert "**confirm** by `test-fixture" in _sections(paths["s2md"].read_text())[case["id"]]
    with pytest.raises(M.ReviewError, match="refusing to overwrite"):
        M.write({paths["s1"]: "case_id\n"})


# --- the committed files -------------------------------------------------------------------------


def test_committed_review_files_are_up_to_date_and_consistent() -> None:
    files = M.build()  # raises on any inconsistent or changed locked answer
    stale = [p.name for p, text in files.items() if not p.exists() or p.read_text() != text]
    assert stale == [], "run: uv run python scripts/b0_review_sheets.py"


def test_labels_stay_ai_proposed_until_a_person_changes_the_dataset() -> None:
    # The generator never edits datasets; this documents the current state.
    for benchmark in M.DATASETS:
        assert all(c["labels"]["status"] == "ai_proposed" for c in _cases(benchmark))
