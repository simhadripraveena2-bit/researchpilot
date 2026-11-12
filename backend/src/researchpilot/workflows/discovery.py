"""W1 Discovery (AGENT_DESIGN §6), M1a scope.

load objective version + plan (deterministic Planner) -> confirm the plan (plain language)
-> search every source (search log) -> resolve hits to works (system of record, dates,
Version Matcher, IN_PROJECT) -> citations among them (OpenAlex metadata, RelationWriter)
-> summary

Stage A assessment, seed selection and citation expansion belong to the Research
Intelligence Engine (M1b) and are not part of this workflow yet.

Durability: every step records its progress in PostgreSQL (plan in the run manifest, search
log, hit outcomes), and LangGraph checkpoints after every node. A crashed run resumes at its
node and skips what is already recorded; a retried run re-sends only failed searches.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

import sqlalchemy as sa
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.db.session import session_scope
from researchpilot.services.discovery import relate, resolve, search, summary
from researchpilot.services.discovery.planner import DiscoveryPlan, PlanOptions, describe, plan
from researchpilot.services.objectives.service import get_objective
from researchpilot.workflows.base import WorkflowDeps, WorkflowSpec


class DiscoveryState(TypedDict, total=False):
    objective_version: int
    plan_id: str
    decision: dict[str, Any]
    outcome: str  # completed | partial | failed | stopped
    error: str


async def set_manifest(session: AsyncSession, run_id: uuid.UUID, key: str, value: Any) -> None:
    """Store one entry under the run manifest's ``discovery`` object."""
    await session.execute(
        sa.text(
            "UPDATE research_runs SET manifest = manifest || jsonb_build_object('discovery', "
            "coalesce(manifest -> 'discovery', '{}'::jsonb) || "
            "jsonb_build_object(CAST(:k AS text), CAST(:v AS jsonb))) WHERE id = :id"
        ),
        {"id": run_id, "k": key, "v": json.dumps(value, default=str)},
    )


async def run_row(session: AsyncSession, run_id: uuid.UUID) -> Any:
    return (
        await session.execute(
            sa.text(
                "SELECT project_id, objective_version, config, manifest FROM research_runs "
                "WHERE id = :id"
            ),
            {"id": run_id},
        )
    ).one()


async def load_plan(session: AsyncSession, run_id: uuid.UUID) -> DiscoveryPlan | None:
    row = await run_row(session, run_id)
    stored = (row.manifest or {}).get("discovery", {}).get("plan")
    return DiscoveryPlan.model_validate(stored) if stored else None


def build(deps: WorkflowDeps) -> StateGraph[DiscoveryState]:
    sources = deps.sources
    options = PlanOptions.model_validate(
        {k: v for k, v in deps.config.items() if k in PlanOptions.model_fields}
    )
    confirm_plan = bool(deps.config.get("confirm_plan", True))
    window_days = int(deps.config.get("release_window_days", summary.DEFAULT_RELEASE_WINDOW_DAYS))

    async def progress(type_: str, message: str) -> None:
        await deps.event(type_, message)

    async def prepare(state: DiscoveryState) -> DiscoveryState:
        await deps.event("step.started", "Reading your research objective")
        async with session_scope(deps.sessions) as session:
            row = await run_row(session, deps.run_id)
            if row.objective_version is None:
                return {"outcome": "failed", "error": "the project has no research objective"}
            existing = await load_plan(session, deps.run_id)
            if existing is None:
                objective = await get_objective(session, row.project_id, row.objective_version)
                existing = plan(objective.id, objective.version, objective.content(), options)
                await set_manifest(session, deps.run_id, "plan", existing.model_dump(mode="json"))
            await search.ensure_queries(session, deps.run_id, existing)
        await deps.event(
            "step.completed",
            f"Prepared {len(existing.queries)} searches from objective version "
            f"{existing.objective_version}",
            plan_id=existing.plan_id,
            objective_version=existing.objective_version,
        )
        # A retried run starts a new pass on the same thread: clear the previous outcome.
        return {
            "objective_version": existing.objective_version,
            "plan_id": existing.plan_id,
            "outcome": "running",
            "error": "",
        }

    async def confirm(state: DiscoveryState) -> DiscoveryState:
        async with session_scope(deps.sessions) as session:
            row = await run_row(session, deps.run_id)
            the_plan = await load_plan(session, deps.run_id)
        assert the_plan is not None
        if not confirm_plan or (row.manifest or {}).get("discovery", {}).get("plan_approved"):
            return {}
        decision = interrupt(
            {
                "name": "confirm_search_plan",
                "question": "Here is how I will search. Shall I go ahead?\n" + describe(the_plan),
                "plan_id": the_plan.plan_id,
                "objective_version": the_plan.objective_version,
            }
        )
        if decision.get("status") == "rejected":
            return {"decision": decision, "outcome": "stopped"}
        async with session_scope(deps.sessions) as session:
            await set_manifest(session, deps.run_id, "plan_approved", True)
        return {"decision": decision}

    async def run_searches(state: DiscoveryState) -> DiscoveryState:
        assert sources is not None, "the discovery workflow needs source clients"
        async with session_scope(deps.sessions) as session:
            the_plan = await load_plan(session, deps.run_id)
        assert the_plan is not None
        await search.execute_searches(deps.sessions, sources, deps.run_id, the_plan, progress)
        return {}

    async def resolve_results(state: DiscoveryState) -> DiscoveryState:
        assert sources is not None
        async with session_scope(deps.sessions) as session:
            row = await run_row(session, deps.run_id)
            the_plan = await load_plan(session, deps.run_id)
        assert the_plan is not None
        await deps.event("step.started", "Reading the papers found and adding them to your project")
        await resolve.resolve_hits(
            deps.sessions,
            sources,
            deps.run_id,
            row.project_id,
            row.objective_version,
            the_plan,
            progress,
        )
        return {}

    async def link_citations(state: DiscoveryState) -> DiscoveryState:
        await deps.ensure_not_cancelled()
        counts = await relate.write_citations(deps.sessions, deps.run_id)
        async with session_scope(deps.sessions) as session:
            await set_manifest(session, deps.run_id, "citations", counts)
        return {}

    async def summarize(state: DiscoveryState) -> DiscoveryState:
        await deps.ensure_not_cancelled()
        async with session_scope(deps.sessions) as session:
            row = await run_row(session, deps.run_id)
            the_plan = await load_plan(session, deps.run_id)
            assert the_plan is not None
            citations = (row.manifest or {}).get("discovery", {}).get("citations")
            result = await summary.build_summary(
                session, deps.run_id, the_plan, datetime.now(UTC), citations, window_days
            )
            await set_manifest(session, deps.run_id, "summary", result)
        searches = result["searches"]
        papers = result["papers"]
        await deps.event(
            "step.completed",
            f"Found {papers['total']} papers ({papers['added']} new to the project) with "
            f"{searches['succeeded']} of {searches['planned']} searches",
        )
        if searches["succeeded"] == 0:
            return {"outcome": "failed", "error": "no search succeeded (see the source report)"}
        if searches["succeeded"] < searches["planned"]:
            return {"outcome": "partial"}
        return {"outcome": "completed"}

    def after(state: DiscoveryState) -> str:
        return END if state.get("outcome") in ("failed", "stopped") else "next"

    graph: StateGraph[DiscoveryState] = StateGraph(DiscoveryState)
    graph.add_node("prepare", prepare)
    graph.add_node("confirm", confirm)
    graph.add_node("search", run_searches)
    graph.add_node("resolve", resolve_results)
    graph.add_node("relate", link_citations)
    graph.add_node("summarize", summarize)
    graph.add_edge(START, "prepare")
    graph.add_conditional_edges("prepare", after, {"next": "confirm", END: END})
    graph.add_conditional_edges("confirm", after, {"next": "search", END: END})
    graph.add_edge("search", "resolve")
    graph.add_edge("resolve", "relate")
    graph.add_edge("relate", "summarize")
    graph.add_edge("summarize", END)
    return graph


def initial_state(config: dict[str, Any]) -> dict[str, Any]:
    return {}


SPEC = WorkflowSpec(name="discovery", version="1", build=build, initial_state=initial_state)
