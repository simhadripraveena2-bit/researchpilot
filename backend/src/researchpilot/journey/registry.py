"""Declarative journey stages (ARCHITECTURE §4.5, A8).

Readiness is derived from project data, never stored. In R0 only the stage skeleton exists:
counts that later releases provide (papers, assessments, ...) are zero, so stages report
what they still need. Adding or changing guidance means editing this registry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from researchpilot.domain.enums import ProjectGoal, StageState


@dataclass(frozen=True)
class ProjectStats:
    """Facts readiness rules may use. R1+ adds fields (papers, analysed papers, gaps, ...)."""

    goal: ProjectGoal
    completed_discovery_runs: int = 0
    included_papers: int = 0
    assessed_papers: int = 0
    papers_with_full_text: int = 0
    analysed_papers: int = 0
    gaps: int = 0
    shortlisted_ideas: int = 0
    experiment_plans: int = 0


@dataclass(frozen=True)
class Stage:
    key: str
    title: str
    state: Callable[[ProjectStats], StageState]
    needs: str  # plain-language explanation shown when not ready
    action: str  # plain-language next action
    available_from: str
    recommended_for: frozenset[ProjectGoal] = field(default_factory=frozenset)


def _ready_if(
    pred: Callable[[ProjectStats], bool], done: Callable[[ProjectStats], bool] = lambda s: False
) -> Callable[[ProjectStats], StageState]:
    def rule(stats: ProjectStats) -> StageState:
        if done(stats):
            return StageState.DONE
        return StageState.READY if pred(stats) else StageState.NOT_READY

    return rule


G = ProjectGoal
STAGES: tuple[Stage, ...] = (
    Stage(
        "discover",
        "Discover",
        _ready_if(lambda s: True, lambda s: s.completed_discovery_runs > 0),
        "Nothing needed",
        "Find papers for your topic",
        "R1",
        frozenset(ProjectGoal),
    ),
    Stage(
        "learn",
        "Learn",
        _ready_if(lambda s: s.included_papers > 0),
        "Find papers first",
        "Read the topic primer and start your reading path",
        "R1",
        frozenset({G.LEARN_FIELD, G.REVIEW_LITERATURE}),
    ),
    Stage(
        "understand",
        "Understand",
        _ready_if(lambda s: s.papers_with_full_text > 0),
        "Open a paper with full text",
        "Read a paper section by section",
        "R1",
        frozenset({G.LEARN_FIELD, G.REVIEW_LITERATURE}),
    ),
    Stage(
        "filter",
        "Filter",
        _ready_if(lambda s: s.assessed_papers > 0),
        "Find papers first",
        "Review what matters for your question",
        "R1",
        frozenset({G.REVIEW_LITERATURE, G.FIND_GAP, G.PLAN_EXPERIMENT, G.TRACK_FIELD}),
    ),
    Stage(
        "compare",
        "Compare",
        _ready_if(lambda s: s.analysed_papers >= 5),
        "Analyse at least 5 papers",
        "Compare methods and results",
        "R2",
        frozenset({G.REVIEW_LITERATURE, G.FIND_GAP}),
    ),
    Stage(
        "investigate",
        "Investigate",
        _ready_if(lambda s: s.analysed_papers >= 10),
        "Analyse at least 10 papers",
        "Look for research gaps",
        "R3",
        frozenset({G.FIND_GAP}),
    ),
    Stage(
        "validate",
        "Validate",
        _ready_if(lambda s: s.gaps > 0),
        "Find a research gap first",
        "Test your ideas against prior work",
        "R3",
        frozenset({G.FIND_GAP, G.WRITE_PROPOSAL}),
    ),
    Stage(
        "experiment",
        "Experiment",
        _ready_if(lambda s: s.shortlisted_ideas > 0),
        "Shortlist an idea first",
        "Plan an experiment",
        "R4",
        frozenset({G.PLAN_EXPERIMENT}),
    ),
    Stage(
        "propose",
        "Propose",
        _ready_if(lambda s: s.experiment_plans > 0),
        "Plan an experiment first",
        "Draft a proposal",
        "R4",
        frozenset({G.WRITE_PROPOSAL}),
    ),
)


class StageView(BaseModel):
    key: str
    title: str
    state: StageState
    needs: str | None
    available_from: str


class NextStep(BaseModel):
    stage: str
    action: str


class JourneyView(BaseModel):
    stages: list[StageView]
    next_step: NextStep


def compute_journey(stats: ProjectStats) -> JourneyView:
    views = [
        StageView(
            key=s.key,
            title=s.title,
            state=(st := s.state(stats)),
            needs=None if st is not StageState.NOT_READY else s.needs,
            available_from=s.available_from,
        )
        for s in STAGES
    ]
    # One recommended next step: the first ready stage recommended for the goal,
    # otherwise the first ready stage.
    ready = [s for s, v in zip(STAGES, views, strict=True) if v.state is StageState.READY]
    chosen = next(
        (s for s in ready if stats.goal in s.recommended_for), ready[0] if ready else STAGES[0]
    )
    return JourneyView(stages=views, next_step=NextStep(stage=chosen.key, action=chosen.action))
