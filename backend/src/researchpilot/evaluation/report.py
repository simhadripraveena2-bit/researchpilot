"""Benchmark reports (Markdown + JSON).

A report always states which split produced the numbers and how the labels were made. For
B3 it contains aggregates and failure categories only - no case ids, identifiers, titles or
explanations (EVALUATION_FRAMEWORK §2a: developers never see B3 items or answers).

"Ready" is never claimed from B0 or from labels that are not expert-adjudicated: a clean B0
run means the rules behave as the development cases expect, not that the release targets are
met.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from researchpilot.evaluation.cases import Dataset, LabelStatus, Split

TARGETS = {
    "G-MATCH": "auto-merge precision >= 0.995; recall >= 0.98 (decisive links) and >= 0.70 "
    "(without; the rest as possible matches); 0 merges of adversarial similar-title pairs; "
    "merges reversible (EVALUATION_FRAMEWORK §3.1)",
    "G-LATEST-DATES": "0 fabricated or mis-typed dates; uncertain dates never confirmed; "
    "journal versions of preprints never new research; revisions never new preprints "
    "(EVALUATION_FRAMEWORK §3.3, §3.8)",
}


def _gates(benchmark: str, m: dict[str, Any]) -> dict[str, bool]:
    if benchmark == "G-MATCH":
        return {
            "every case evaluable": not m["not_evaluable"],
            "no false-positive merge": not m["false_positive_merges"],
            "no adversarial merge": not m["adversarial_merges"],
            "no ambiguous pair merged": not m["ambiguous_merged"],
            "no order dependence": not m["order_dependent"],
            "merges reversible": m["reversible"] in (None, 1.0),
            "rejections sticky": m["rejection_sticky"] in (None, 1.0),
        }
    return {
        "every case evaluable": not m["not_evaluable"],
        "no incorrectly verified date": not m["incorrectly_verified"],
        "no uncertain date shown as confirmed": not m["uncertain_shown_as_confirmed"],
        "no journal date over an earlier preprint": not m["journal_date_over_preprint"],
        "no revision shown as new work": not m["revision_shown_as_new_work"],
    }


def build(
    dataset: Dataset,
    results: list[dict[str, Any]],
    m: dict[str, Any],
    run_info: dict[str, str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """``run_info``: what makes the run reproducible (git SHA, rule versions, dataset hash;
    EVALUATION_FRAMEWORK §4)."""
    run_info = run_info or {}
    cases = dataset.match_cases or dataset.date_cases
    labels = Counter(c.labels.status.value for c in cases)
    provenance = Counter(c.provenance.value for c in cases)
    categories = Counter(c.category for c in cases)
    aggregate_only = dataset.split is Split.B3
    gates = _gates(dataset.benchmark, m)
    expert = labels.get(LabelStatus.EXPERT_ADJUDICATED.value, 0) == len(cases)
    gates_pass = all(gates.values())
    if dataset.split is Split.B0 or not expert:
        verdict = (
            "NOT a release decision: "
            + ("B0 development split" if dataset.split is Split.B0 else "labels not expert")
            + ("; all gates pass on these cases" if gates_pass else "; gates FAIL - see failures")
            + ". Release targets can only be judged on expert-labelled B3 run by the custodian."
        )
    elif dataset.split is Split.B3:
        verdict = "Gates pass on B3" if gates_pass else "Gates FAIL on B3"
    else:
        verdict = (
            f"{dataset.split.value} (calibration/expanded): "
            + ("gates pass" if gates_pass else "gates FAIL")
            + "; not a release decision"
        )

    by_id = {c.id: c for c in cases}
    failures = [r for r in results if not r.get("correct") or r.get("error")]
    lines = [
        f"# {dataset.benchmark} - split {dataset.split.value} (dataset {dataset.version})",
        "",
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by "
        "`scripts/run_benchmarks.py`. **Split: " + dataset.split.value + ".**",
        "",
        *(f"- {k}: `{v}`" for k, v in run_info.items()),
        "",
        "## Verdict",
        "",
        verdict,
        "",
        "## Dataset",
        "",
        dataset.description,
        "",
        f"- Cases: {len(cases)}; categories: "
        + ", ".join(f"{k} {v}" for k, v in sorted(categories.items())),
        "- Provenance: " + ", ".join(f"{k} {v}" for k, v in sorted(provenance.items())),
        "- Labels: "
        + ", ".join(f"{k} {v}" for k, v in sorted(labels.items()))
        + (
            " - **AI-proposed labels are not gold** (EVALUATION_FRAMEWORK §2a): they await "
            "review against primary pages by a team member."
            if labels.get(LabelStatus.AI_PROPOSED.value)
            else ""
        ),
        "",
        "## Methodology",
        "",
        "Each case runs the production code paths on a scratch database from recorded "
        "source responses (no network): ingestion from the system of record, version links, "
        "the Version Matcher, the Date Resolver, announcement capture and the release-type "
        "classifier. Unrecorded aggregator lookups (OpenAlex, Semantic Scholar) are answered "
        "'unavailable'; unrecorded system-of-record requests make a case not evaluable "
        "(never scored).",
        "",
        f"Targets: {TARGETS[dataset.benchmark]}.",
        "",
        "## Gates",
        "",
        *(f"- [{'x' if ok else ' '}] {name}" for name, ok in gates.items()),
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    for key, value in m.items():
        if key in ("confusion", "by_category"):
            continue
        shown = (
            value
            if not isinstance(value, list)
            else (f"{len(value)}" if aggregate_only else (", ".join(value) or "none"))
        )
        lines.append(f"| {key} | {shown} |")
    lines += ["", "### Expected -> observed", "", "| Pair | Count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in m["confusion"].items()]
    lines += ["", "### By category", "", "| Category | Cases | Correct |", "|---|---|---|"]
    lines += [f"| {k} | {v['cases']} | {v['correct']} |" for k, v in m["by_category"].items()]
    lines += ["", "## Failures", ""]
    if not failures:
        lines.append("None.")
    elif aggregate_only:
        lines.append(f"{len(failures)} failing cases (B3: details withheld; categories above).")
    else:
        for r in failures:
            case = by_id[r["case_id"]]
            lines.append(f"- **{r['case_id']}** ({case.category}): {r.get('error') or ''}")
            lines.append(f"  - expected: {_expected(case)}; observed: {_observed(r)}")
            lines.append(f"  - why expected: {case.explanation}")
    lines.append("")
    payload = {
        "benchmark": dataset.benchmark,
        "split": dataset.split.value,
        "dataset_version": dataset.version,
        "run": run_info,
        "labels": dict(labels),
        "provenance": dict(provenance),
        "gates": gates,
        "verdict": verdict,
        "metrics": m if not aggregate_only else _aggregate(m),
        "results": [] if aggregate_only else results,
    }
    return "\n".join(lines), payload


def _aggregate(m: dict[str, Any]) -> dict[str, Any]:
    return {k: (len(v) if isinstance(v, list) else v) for k, v in m.items()}


def _expected(case: Any) -> str:
    e = case.expected
    if hasattr(e, "outcome"):
        return f"{e.relationship}, {e.outcome.value}"
    return (
        f"{e.first_public_date or 'none'} ({e.basis.value if e.basis else '-'}), "
        f"{e.confidence.value}" + (f", release {e.release_type}" if e.release_type else "")
    )


def _observed(r: dict[str, Any]) -> str:
    o = r.get("observed")
    if not o:
        return "-"
    if "merged" in o:
        rev = r.get("reversed_order") or {}
        return f"{o['outcome']} (reversed order: {rev.get('outcome')})"
    return (
        f"{o['first_public_date'] or 'none'} ({o['basis'] or '-'}), {o['confidence']}"
        + (f", release {o['release_type']}" if o.get("release_type") else "")
        + ("" if o.get("one_work", True) else ", NOT one work")
    )


def write(out_dir: Path, dataset: Dataset, markdown: str, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{dataset.benchmark.lower()}-{dataset.split.value.lower()}"
    (out_dir / f"{stem}.md").write_text(markdown)
    (out_dir / f"{stem}.json").write_text(json.dumps(payload, indent=1, default=str) + "\n")
    return out_dir / f"{stem}.md"
