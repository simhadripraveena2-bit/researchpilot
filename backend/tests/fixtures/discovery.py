"""The objective and options of the recorded end-to-end discovery run.

``scripts/record_discovery_fixtures.py`` ran exactly this against the real APIs and saved
every response under ``tests/fixtures/sources``; the tests replay them (no network).
"""

from __future__ import annotations

from typing import Any

OBJECTIVE: dict[str, Any] = {
    "core_question": "Which graph neural networks work best for molecular property prediction?",
    "sub_questions": [
        {"text": "Which benchmarks are used to evaluate molecular property prediction?"},
        {"text": "How does message passing compare with graph transformers?"},
    ],
    "domain": "machine learning",
    "target_tasks": ["molecular property prediction"],
    "keywords": ["graph neural network"],
    "synonyms": {"graph neural network": ["GNN"]},
    "exclusions": ["protein folding"],
    "constraints": {
        "methods": {"preferred": ["message passing"], "avoided": ["reinforcement learning"]},
        "compute": {"gpu_hours": 50},
    },
    "expected_outcomes": ["a shortlist of methods and benchmarks"],
}

RUN_CONFIG: dict[str, Any] = {
    "max_queries": 4,
    "max_results_per_query": 5,
    "max_candidates": 12,
    "confirm_plan": False,
}
