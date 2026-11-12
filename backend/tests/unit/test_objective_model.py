"""Research objective content: field limits, hard validation and completeness (pure)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from researchpilot.services.objectives.model import (
    MAX_SUB_QUESTIONS,
    ObjectiveContent,
    completeness,
    validate,
)


def full(**overrides: Any) -> ObjectiveContent:
    data: dict[str, Any] = {
        "core_question": "Which GNN architectures predict molecular properties best?",
        "sub_questions": [
            {"text": "Which benchmarks are used?"},
            {"text": "How do message-passing and transformer models compare?"},
        ],
        "domain": "machine learning",
        "subdomains": ["graph learning"],
        "target_tasks": ["molecular property prediction"],
        "problem_areas": ["data scarcity"],
        "focus_concepts": ["message passing"],
        "keywords": ["GNN", "molecular graphs"],
        "synonyms": {"GNN": ["graph neural network", "GNN"]},
        "exclusions": ["protein folding"],
        "constraints": {
            "methods": {"preferred": ["GNN"], "avoided": ["LLM fine-tuning"]},
            "datasets": {"required": ["QM9"], "open_access_only": True},
            "benchmarks": {"preferred": ["MoleculeNet"]},
            "compute": {
                "gpu_hours": 100,
                "hardware": ["one A100"],
                "max_cost": 500,
                "currency": "EUR",
            },
            "time": {"horizon": "3 months", "deadline": "2027-03-01"},
            "resources": ["one PhD student"],
            "licences": ["commercial use"],
        },
        "expected_outcomes": ["a ranked shortlist of methods"],
        "user_context": "I work in a pharma lab.",
        "notes": "Prefer recent work.",
    }
    data.update(overrides)
    return ObjectiveContent.model_validate(data)


def test_complete_objective_has_no_errors_or_gaps() -> None:
    report = completeness(full())
    assert report.complete, report
    assert report.errors == [] and report.missing == []


def test_terms_are_trimmed_and_deduplicated_case_insensitively() -> None:
    content = full(keywords=["  GNN ", "gnn", "Graphs"], synonyms={"GNN": ["a", "A", "b"]})
    assert content.keywords == ["GNN", "Graphs"]
    assert content.synonyms == {"GNN": ["a", "b"]}


def test_incomplete_objective_lists_what_is_missing_but_is_valid() -> None:
    content = ObjectiveContent(core_question="What is diffusion?")
    report = completeness(content)
    assert not report.complete
    assert report.errors == []
    assert {i.field for i in report.missing} == {
        "sub_questions",
        "domain",
        "target_tasks",
        "keywords",
        "expected_outcomes",
    }


@pytest.mark.parametrize(
    "data",
    [
        {"core_question": ""},
        {"core_question": "  "},
        {"core_question": "x" * 1001},
        {"core_question": "Valid?", "keywords": [""]},
        {"core_question": "Valid?", "keywords": ["k"] * 51},
        {"core_question": "Valid?", "unknown_field": 1},
        {"core_question": "Valid?", "constraints": {"compute": {"gpu_hours": -1}}},
        {"core_question": "Valid?", "constraints": {"time": {"deadline": "next week"}}},
        {"core_question": "Valid?", "constraints": {"surprise": {}}},
        {"core_question": "Valid?", "sub_questions": [{"text": "no"}]},
    ],
)
def test_field_limits_are_rejected(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ObjectiveContent.model_validate(data)


def test_hard_rules() -> None:
    too_many = full(sub_questions=[{"text": f"question {i}"} for i in range(MAX_SUB_QUESTIONS + 1)])
    assert [i.code for i in validate(too_many)] == ["too_many"]
    dup_keys = full(sub_questions=[{"key": "SQ1", "text": "first"}, {"key": "SQ1", "text": "two"}])
    assert [i.code for i in validate(dup_keys)] == ["duplicate_key"]
    bad_key = full(sub_questions=[{"key": "Q1", "text": "first one"}])
    assert [i.code for i in validate(bad_key)] == ["bad_key"]
    dup_text = full(sub_questions=[{"text": "Same thing"}, {"text": "same thing"}])
    assert [i.code for i in validate(dup_text)] == ["duplicate_text"]


def test_contradictions_are_errors() -> None:
    clash = full(exclusions=["GNN"], keywords=["gnn"])
    assert [(i.field, i.code) for i in validate(clash)] == [("exclusions", "contradiction")]
    data = full(constraints={"datasets": {"required": ["QM9"], "excluded": ["qm9"]}})
    assert [i.field for i in validate(data)] == ["constraints.datasets"]
    methods = full(constraints={"methods": {"preferred": ["RL"], "avoided": ["RL"]}})
    assert [i.field for i in validate(methods)] == ["constraints.methods"]
    report = completeness(clash)
    assert not report.complete and report.errors
