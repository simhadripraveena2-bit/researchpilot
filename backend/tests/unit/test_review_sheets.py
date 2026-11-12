"""The B0 review sheets are generated from the datasets and recordings and must stay in
sync with them; they never mark an AI-proposed label as reviewed."""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

BACKEND = Path(__file__).resolve().parents[2]


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "b0_review_sheets", BACKEND / "scripts" / "b0_review_sheets.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


def test_review_sheets_are_up_to_date() -> None:
    m = _module()
    stale = [p.name for p, text in m.build().items() if not p.exists() or p.read_text() != text]
    assert stale == [], "run: uv run python scripts/b0_review_sheets.py"


def test_every_case_has_a_sheet_entry_and_review_status_matches_decisions() -> None:
    m = _module()
    for benchmark, path in m.DATASETS.items():
        data = json.loads(path.read_text())
        cases = data.get("match_cases") or data.get("date_cases")
        stem = benchmark.lower().replace("-", "_")
        sheet = (m.OUT / f"{stem.upper()}_B0_REVIEW.md").read_text()
        with (m.OUT / f"{stem}_b0_decisions.csv").open(newline="") as handle:
            rows = {r["case_id"]: r for r in csv.DictReader(handle)}
        assert set(rows) == {c["id"] for c in cases}  # one decision row per case
        for case in cases:
            assert f"## {case['id']} " in sheet
        decided = sum(1 for r in rows.values() if r["decision"])
        assert f"**{decided} / {len(cases)}**" in sheet
        # Labels stay AI-proposed until a person edits the dataset after review.
        if decided == 0:
            assert all(c["labels"]["status"] == "ai_proposed" for c in cases)
            assert sheet.count("not reviewed (label is AI-proposed)") == len(cases)
