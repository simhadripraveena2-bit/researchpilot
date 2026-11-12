"""Deterministic discovery Planner (pure)."""

from __future__ import annotations

import uuid
from typing import Any

from researchpilot.domain.enums import SearchOrigin, SourceName
from researchpilot.services.discovery.planner import (
    PlanOptions,
    describe,
    keywords,
    matches,
    phrase_terms,
    plan,
    render_arxiv,
)
from researchpilot.services.objectives.model import ObjectiveContent
from tests.fixtures.discovery import OBJECTIVE

OBJ_ID = uuid.UUID(int=7)


def content(**overrides: Any) -> ObjectiveContent:
    data = {**OBJECTIVE, **overrides}
    c = ObjectiveContent.model_validate(data)
    keyed = [s.model_copy(update={"key": f"SQ{i}"}) for i, s in enumerate(c.sub_questions, 1)]
    return c.model_copy(update={"sub_questions": keyed})


def test_core_question_and_every_sub_question_have_a_query() -> None:
    p = plan(OBJ_ID, 3, content())
    assert p.objective_id == OBJ_ID and p.objective_version == 3
    core = p.queries[0]
    assert (core.id, core.purpose, core.origin) == ("Q1", "core", SearchOrigin.PLANNER)
    # The user's phrase stays whole (also in plural) and carries its synonym.
    assert core.terms[0] == ["graph neural network", "GNN"]
    assert ["molecular property prediction"] in core.terms
    assert set(p.sub_question_queries) == {"SQ1", "SQ2"}
    for key, ids in p.sub_question_queries.items():
        own = [p.query(i) for i in ids if key in p.query(i).sub_question_keys]
        assert own and own[0].purpose == "sub_question"
    sq2 = p.query(p.sub_question_queries["SQ2"][0])
    assert ["message passing"] in sq2.terms  # a preferred method named in the sub-question
    assert [q.id for q in p.queries] == [f"Q{i}" for i in range(1, len(p.queries) + 1)]
    assert len({q.text for q in p.queries}) == len(p.queries)


def test_short_sub_questions_are_anchored_on_the_main_topic() -> None:
    p = plan(OBJ_ID, 1, content(sub_questions=[{"text": "Which benchmarks are used?"}]))
    sq = p.query(p.sub_question_queries["SQ1"][0])
    assert sq.terms[0] == ["molecular property prediction"]
    assert sq.text == "molecular property prediction benchmarks"


def test_plans_are_deterministic_and_identify_their_inputs() -> None:
    a = plan(OBJ_ID, 1, content())
    assert a == plan(OBJ_ID, 1, content())
    assert a.plan_id != plan(OBJ_ID, 2, content()).plan_id
    assert a.plan_id != plan(OBJ_ID, 1, content(), PlanOptions(max_results_per_query=5)).plan_id
    assert a.plan_id != plan(OBJ_ID, 1, content(exclusions=["docking"])).plan_id


def test_exclusions_are_hard_filters_and_avoided_methods_are_flags() -> None:
    p = plan(OBJ_ID, 1, content())
    assert p.excluded_terms == ["protein folding"]
    assert p.flagged_terms == ["reinforcement learning"]
    for q in p.queries:
        assert q.rendered["arxiv_api"].endswith('ANDNOT all:"protein folding"')
        assert "protein" not in q.rendered["crossref"]  # no negation: filtered on results
    assert matches(p.excluded_terms, "Learning Protein-Folding pathways", None) == [
        "protein folding"
    ]
    assert matches(p.excluded_terms, "Proteins folding into shapes", "") == []
    assert "will be left out" in describe(p) and "kept but marked" in describe(p)


def test_expansions_follow_the_budget_and_never_drop_core_or_sub_questions() -> None:
    small = plan(OBJ_ID, 1, content(), PlanOptions(max_queries=1))
    assert [q.purpose for q in small.queries] == ["core", "sub_question", "sub_question"]
    large = plan(
        OBJ_ID,
        1,
        content(
            focus_concepts=["molecular graphs"],
            constraints={
                "methods": {"preferred": ["message passing"]},
                "datasets": {"required": ["QM9"]},
                "benchmarks": {"preferred": ["MoleculeNet"]},
            },
        ),
        PlanOptions(max_queries=20),
    )
    purposes = [q.purpose for q in large.queries]
    assert purposes[:3] == ["core", "sub_question", "sub_question"]
    assert {"synonym", "task", "concept", "method", "dataset"} <= set(purposes)
    assert all(q.origin is SearchOrigin.RULE_EXPANSION for q in large.queries[3:])
    texts = [q.text for q in large.queries]
    assert "QM9 molecular property prediction" in texts
    assert "MoleculeNet molecular property prediction" in texts


def test_sources_per_query_and_why_others_are_not_searched() -> None:
    p = plan(OBJ_ID, 1, content())
    used = {c.source for c in p.sources if c.used}
    assert used == {
        SourceName.ARXIV_API,
        SourceName.CROSSREF,
        SourceName.SEMANTIC_SCHOLAR,
        SourceName.OPENALEX,
    }
    biorxiv = next(c for c in p.sources if c.source is SourceName.BIORXIV_API)
    assert not biorxiv.used and "no topic search" in biorxiv.reason
    assert all(set(q.sources) == used for q in p.queries)

    clinical = plan(OBJ_ID, 1, content(domain="clinical medicine"))
    arxiv = next(c for c in clinical.sources if c.source is SourceName.ARXIV_API)
    assert not arxiv.used and "clinical" in arxiv.reason
    assert all(SourceName.ARXIV_API not in q.sources for q in clinical.queries)
    assert (
        "life-science"
        in next(c for c in clinical.sources if c.source is SourceName.MEDRXIV_API).reason
    )

    only = plan(OBJ_ID, 1, content(), PlanOptions(sources=[SourceName.CROSSREF]))
    assert {c.source for c in only.sources if c.used} == {SourceName.CROSSREF}
    assert all(set(q.rendered) == {"crossref"} for q in only.queries)


def test_constraints_that_do_not_shape_a_search_are_stated() -> None:
    p = plan(
        OBJ_ID,
        1,
        content(
            constraints={
                "compute": {"gpu_hours": 10},
                "time": {"horizon": "3 months"},
                "resources": ["one student"],
                "datasets": {"open_access_only": True},
            }
        ),
    )
    assert len(p.not_applied) == 4
    assert any("compute" in n for n in p.not_applied)


def test_text_helpers() -> None:
    assert keywords("Which of the methods work best for drug discovery?") == [
        "methods",
        "drug",
        "discovery",
    ]
    assert phrase_terms(
        "How do graph neural networks handle drug discovery?",
        ["graph neural network", "drug discovery"],
        4,
    ) == ["graph neural network", "handle", "drug discovery"]  # in order of appearance
    assert render_arxiv([["a b", "c"], ["d"]], ["x y"]) == (
        '(all:"a b" OR all:c) AND all:d ANDNOT all:"x y"'
    )
