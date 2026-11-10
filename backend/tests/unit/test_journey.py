"""R0-7: nine stages with deterministic states and exactly one next step."""

from __future__ import annotations

import pytest

from researchpilot.domain.enums import ProjectGoal, StageState
from researchpilot.journey.registry import STAGES, ProjectStats, compute_journey

EXPECTED_ORDER = [
    "discover",
    "learn",
    "understand",
    "filter",
    "compare",
    "investigate",
    "validate",
    "experiment",
    "propose",
]


def test_nine_stages_in_order() -> None:
    assert [s.key for s in STAGES] == EXPECTED_ORDER


@pytest.mark.parametrize("goal", list(ProjectGoal))
def test_new_project_journey_is_deterministic(goal: ProjectGoal) -> None:
    first = compute_journey(ProjectStats(goal=goal))
    second = compute_journey(ProjectStats(goal=goal))
    assert first == second
    states = {s.key: s.state for s in first.stages}
    assert states["discover"] is StageState.READY
    assert all(states[k] is StageState.NOT_READY for k in EXPECTED_ORDER[1:])
    assert all(s.needs for s in first.stages if s.state is StageState.NOT_READY)
    assert first.next_step.stage == "discover"


def test_next_step_follows_goal_once_papers_exist() -> None:
    stats = dict(completed_discovery_runs=1, included_papers=10, assessed_papers=10)
    learn = compute_journey(ProjectStats(goal=ProjectGoal.LEARN_FIELD, **stats))
    gap = compute_journey(ProjectStats(goal=ProjectGoal.FIND_GAP, **stats))
    assert {s.key: s.state for s in learn.stages}["discover"] is StageState.DONE
    assert learn.next_step.stage == "learn"
    assert gap.next_step.stage == "filter"
