"""The research objective as data: what the user wants to find, and validation rules.

Pure (no I/O). ``ObjectiveContent`` is what one version holds; ``validate`` reports hard
errors (the version cannot be saved) and ``completeness`` reports what is still missing
before discovery and relevance assessment can use the objective well (it can be saved).
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from researchpilot.domain.enums import ExpertiseLevel, ProjectGoal

MAX_SUB_QUESTIONS = 6  # RIE §2.1: 2-6
MIN_SUB_QUESTIONS = 2
MAX_LIST_ITEMS = 50
SUB_QUESTION_KEY = re.compile(r"^SQ[1-9][0-9]*$")

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
Terms = Annotated[list[Short], Field(max_length=MAX_LIST_ITEMS)]


def _dedupe(values: list[str]) -> list[str]:
    """Keep the first spelling of each term (case-insensitive); order is preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v.casefold() not in seen:
            seen.add(v.casefold())
            out.append(v)
    return out


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MethodConstraints(_Strict):
    preferred: Terms = []
    avoided: Terms = []
    required: Terms = []


class DataConstraints(_Strict):
    """Datasets or benchmarks the work must, should or must not use."""

    required: Terms = []
    preferred: Terms = []
    excluded: Terms = []
    open_access_only: bool = False


class ComputeConstraints(_Strict):
    gpu_hours: float | None = Field(default=None, ge=0)
    hardware: Terms = []  # e.g. "single consumer GPU", "CPU only"
    max_cost: float | None = Field(default=None, ge=0)
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] | None = None


class TimeConstraints(_Strict):
    horizon: Short | None = None  # e.g. "3 months"
    deadline: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")] | None = None


class Constraints(_Strict):
    """Methodological, data, benchmark, compute, time and resource constraints."""

    methods: MethodConstraints = MethodConstraints()
    datasets: DataConstraints = DataConstraints()
    benchmarks: DataConstraints = DataConstraints()
    compute: ComputeConstraints = ComputeConstraints()
    time: TimeConstraints = TimeConstraints()
    resources: Terms = []  # people, access, tools
    licences: Terms = []  # licence needs, e.g. "commercial use"
    other: Terms = []


class SubQuestionIn(_Strict):
    """``key`` is given to keep an existing sub-question's identity; new ones omit it."""

    key: str | None = None
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class ObjectiveContent(_Strict):
    core_question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)
    ]
    sub_questions: Annotated[list[SubQuestionIn], Field(max_length=20)] = []
    domain: Short | None = None
    subdomains: Terms = []
    target_tasks: Terms = []
    problem_areas: Terms = []
    focus_concepts: Terms = []  # must-cover and related concepts
    keywords: Terms = []
    synonyms: Annotated[dict[Short, Terms], Field(max_length=MAX_LIST_ITEMS)] = {}
    exclusions: Terms = []  # out-of-scope topics and methods
    constraints: Constraints = Constraints()
    expected_outcomes: Terms = []
    user_context: LongText | None = None
    notes: LongText | None = None
    expertise_level: ExpertiseLevel | None = None  # default: the project's
    goal: ProjectGoal | None = None  # default: the project's

    @field_validator(
        "subdomains",
        "target_tasks",
        "problem_areas",
        "focus_concepts",
        "keywords",
        "exclusions",
        "expected_outcomes",
    )
    @classmethod
    def _unique_terms(cls, v: list[str]) -> list[str]:
        return _dedupe(v)

    @field_validator("synonyms")
    @classmethod
    def _unique_synonyms(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        return {term: _dedupe(values) for term, values in v.items()}


class Issue(BaseModel):
    field: str
    code: str
    message: str


class Completeness(BaseModel):
    complete: bool
    errors: list[Issue]  # the version cannot be saved
    missing: list[Issue]  # it can be saved; discovery and assessment work less well


def validate(content: ObjectiveContent) -> list[Issue]:
    """Hard rules beyond field limits."""
    issues: list[Issue] = []
    sqs = content.sub_questions
    if len(sqs) > MAX_SUB_QUESTIONS:
        issues.append(
            Issue(
                field="sub_questions",
                code="too_many",
                message=f"at most {MAX_SUB_QUESTIONS} sub-questions",
            )
        )
    keys = [s.key for s in sqs if s.key is not None]
    for key in keys:
        if not SUB_QUESTION_KEY.match(key):
            issues.append(
                Issue(field="sub_questions", code="bad_key", message=f"invalid key {key!r}")
            )
    if len(keys) != len(set(keys)):
        issues.append(Issue(field="sub_questions", code="duplicate_key", message="duplicate keys"))
    texts = [s.text.casefold() for s in sqs]
    if len(texts) != len(set(texts)):
        issues.append(
            Issue(field="sub_questions", code="duplicate_text", message="duplicate sub-questions")
        )
    excluded = {e.casefold() for e in content.exclusions}
    for field in ("keywords", "focus_concepts", "target_tasks", "problem_areas"):
        clash = [t for t in getattr(content, field) if t.casefold() in excluded]
        if clash:
            issues.append(
                Issue(
                    field="exclusions",
                    code="contradiction",
                    message=f"excluded and also in {field}: {', '.join(clash)}",
                )
            )
    for kind in ("datasets", "benchmarks"):
        data: DataConstraints = getattr(content.constraints, kind)
        clash = sorted(
            {t.casefold() for t in data.required + data.preferred}
            & {t.casefold() for t in data.excluded}
        )
        if clash:
            issues.append(
                Issue(
                    field=f"constraints.{kind}",
                    code="contradiction",
                    message=f"both wanted and excluded: {', '.join(clash)}",
                )
            )
    methods = content.constraints.methods
    clash = sorted(
        {t.casefold() for t in methods.required + methods.preferred}
        & {t.casefold() for t in methods.avoided}
    )
    if clash:
        issues.append(
            Issue(
                field="constraints.methods",
                code="contradiction",
                message=f"both wanted and avoided: {', '.join(clash)}",
            )
        )
    return issues


def completeness(content: ObjectiveContent) -> Completeness:
    errors = validate(content)
    missing: list[Issue] = []

    def need(ok: bool, field: str, message: str) -> None:
        if not ok:
            missing.append(Issue(field=field, code="missing", message=message))

    need(
        len(content.sub_questions) >= MIN_SUB_QUESTIONS,
        "sub_questions",
        f"add at least {MIN_SUB_QUESTIONS} sub-questions",
    )
    need(content.domain is not None, "domain", "name the research domain")
    need(
        bool(content.target_tasks or content.problem_areas),
        "target_tasks",
        "add a task or problem area",
    )
    need(
        bool(content.keywords or content.focus_concepts),
        "keywords",
        "add keywords or focus concepts",
    )
    need(bool(content.expected_outcomes), "expected_outcomes", "say what you expect to get")
    return Completeness(complete=not errors and not missing, errors=errors, missing=missing)


__all__ = [
    "MAX_SUB_QUESTIONS",
    "MIN_SUB_QUESTIONS",
    "Completeness",
    "Constraints",
    "Issue",
    "ObjectiveContent",
    "SubQuestionIn",
    "completeness",
    "validate",
]
