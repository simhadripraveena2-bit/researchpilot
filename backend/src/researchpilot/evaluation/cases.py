"""Benchmark cases, datasets and split rules (EVALUATION_FRAMEWORK §2-2b).

A dataset is one split (B0-B3) of one benchmark (G-MATCH or G-LATEST-DATES). Every case
records its label provenance: who proposed the label, who reviewed and approved it, and the
guideline version. Only B0 may hold AI-proposed or unreviewed labels; B1-B3 need expert
labels (two annotators, adjudication, approval). AI-generated labels are never gold.

B3 (held-out) is never stored in this repository and never read by developers or AI
assistants; only the benchmark custodian runs it, from custodian storage, and B3 reports
contain aggregates only (``guard_split``, ``report.py``).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from researchpilot.domain.enums import DateConfidence, FirstPublicBasis, MatchOutcome, ReleaseType
from researchpilot.domain.identifiers import InvalidIdentifier, parse_identifier

REPO_ROOT = Path(__file__).resolve().parents[4]
CUSTODIAN_ENV = "RP_BENCHMARK_CUSTODIAN"


class Split(StrEnum):
    B0 = "B0"  # development: team labels allowed (marked); tests, debugging
    B1 = "B1"  # calibration: expert labels
    B2 = "B2"  # expanded expert evaluation
    B3 = "B3"  # locked held-out: custodian only


class LabelStatus(StrEnum):
    AI_PROPOSED = "ai_proposed"  # pre-annotation by an AI assistant: never gold (B0 only)
    TEAM_REVIEWED = "team_reviewed"  # checked by a team member against primary pages (B0)
    EXPERT_ADJUDICATED = "expert_adjudicated"  # 2 annotators + adjudication + approval


class Provenance(StrEnum):
    RECORDED = "recorded"  # built from real, recorded source responses
    SYNTHETIC = "synthetic"  # constructed records: rule tests only, never evaluation evidence


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Labels(_Strict):
    status: LabelStatus
    guideline: str
    proposed_by: str  # e.g. "ai-assistant" or an annotator handle
    annotators: list[str] = []
    adjudicator: str | None = None
    approved_by: str | None = None


CaseId = Annotated[str, Field(pattern=r"^G(M|D)-B[0-3]-[0-9]{3}$")]


class MatchExpectation(_Strict):
    relationship: Literal["same_work", "related_not_same", "different"]
    outcome: MatchOutcome  # the matcher's correct output for this pair
    auto_merge_allowed: bool
    user_confirmation_required: bool
    decisive_evidence: bool  # an explicit identifier/version link exists in the records


class MatchCase(_Strict):
    id: CaseId
    category: Literal[
        "preprint_journal",
        "preprint_versions",
        "similar_title_different",
        "part_series",
        "explicit_link_different_title",
        "comment_reply",
        "correction_notice",
        "related_extends",
        "ambiguous_no_link",
    ]
    adversarial: bool
    a: str  # identifier (DOI, arXiv ID, ...) whose recorded records define work A
    b: str
    expected: MatchExpectation
    explanation: str
    evidence: list[str]
    provenance: Provenance
    labels: Labels

    @field_validator("a", "b")
    @classmethod
    def _identifier(cls, value: str) -> str:
        try:
            parse_identifier(value)
        except InvalidIdentifier as exc:  # reported as a validation error of the case
            raise ValueError(f"unsupported identifier {value!r}: {exc}") from exc
        return value


class DateExpectation(_Strict):
    first_public_date: date | None  # None: no first public appearance may be set
    basis: FirstPublicBasis | None
    confidence: DateConfidence
    first_public_kind: Literal["preprint", "published", "other"] | None = None
    candidate_public_date: date | None = None  # shown only as unconfirmed
    # Optional release-type check: the window (inclusive UTC days) and the expected type.
    window: tuple[date, date] | Literal["run_day"] | None = None
    release_type: ReleaseType | Literal["none"] | None = None


class DateCase(_Strict):
    id: CaseId
    category: Literal[
        "arxiv_announced",
        "arxiv_submission_only",
        "arxiv_cross_listing",
        "arxiv_revision",
        "server_posted",
        "journal_of_older_preprint",
        "journal_only",
        "conflicting",
        "reduced_precision",
        "metadata_vs_public",
        "newly_indexed_older",
        "insufficient_evidence",
    ]
    identifiers: list[str]  # ingested in this order (one work, possibly several versions)
    capture_feeds: list[str] = []  # arXiv RSS categories to capture after ingesting
    expected: DateExpectation
    explanation: str
    evidence: list[str]
    provenance: Provenance
    labels: Labels


class Dataset(_Strict):
    benchmark: Literal["G-MATCH", "G-LATEST-DATES"]
    split: Split
    version: str
    description: str
    recordings: list[str]  # directories of recorded responses, relative to the dataset file
    match_cases: list[MatchCase] = []
    date_cases: list[DateCase] = []


class SplitViolation(Exception):
    pass


def guard_split(dataset: Dataset, path: Path) -> None:
    """Refuse data that breaks the protocol before anything is run."""
    cases: list[MatchCase | DateCase] = [*dataset.match_cases, *dataset.date_cases]
    for case in cases:
        if not case.id.startswith(f"{case.id[:2]}-{dataset.split.value}-"):
            raise SplitViolation(f"{case.id} is not a {dataset.split.value} case id")
    if dataset.split is Split.B0:
        return
    weak = [c.id for c in cases if c.labels.status is not LabelStatus.EXPERT_ADJUDICATED]
    if weak:
        raise SplitViolation(
            f"{dataset.split.value} needs expert-adjudicated labels; not: {', '.join(weak[:5])}"
        )
    synthetic = [c.id for c in cases if c.provenance is Provenance.SYNTHETIC]
    if synthetic:
        raise SplitViolation(f"synthetic cases are not evaluation data: {', '.join(synthetic)}")
    if dataset.split is Split.B3:
        if path.resolve().is_relative_to(REPO_ROOT):
            raise SplitViolation("B3 data must not be stored in the repository")
        if os.environ.get(CUSTODIAN_ENV) != "1":
            raise SplitViolation(f"B3 is run by the benchmark custodian only ({CUSTODIAN_ENV}=1)")


def load_dataset(path: Path) -> Dataset:
    dataset = Dataset.model_validate(json.loads(path.read_text()))
    guard_split(dataset, path)
    ids = [c.id for c in dataset.match_cases] + [c.id for c in dataset.date_cases]
    if len(ids) != len(set(ids)):
        raise SplitViolation("duplicate case ids")
    return dataset


def work_keys(dataset: Dataset) -> set[str]:
    """Hashes of the works a split uses (splits are made by work: none may share one)."""
    keys: set[str] = set()
    for m in dataset.match_cases:
        keys |= {m.a.lower(), m.b.lower()}
    for d in dataset.date_cases:
        keys |= {i.lower() for i in d.identifiers}
    return {hashlib.sha256(k.encode()).hexdigest() for k in keys}


def overlapping_works(datasets: list[Dataset]) -> dict[tuple[str, str], int]:
    """(split, split) -> number of shared works; must be empty (EVALUATION §2a)."""
    out: dict[tuple[str, str], int] = {}
    for i, a in enumerate(datasets):
        for b in datasets[i + 1 :]:
            if a.split is b.split:
                continue
            shared = len(work_keys(a) & work_keys(b))
            if shared:
                out[(a.split.value, b.split.value)] = shared
    return out
