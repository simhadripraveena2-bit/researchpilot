"""Read side of a discovery run: search history, sources, discovered papers and the summary.

Everything is computed from the stored search log, project items, dates and match decisions;
release types are classified on read with the existing classifier, so the summary always
reflects the current state of each work (e.g. after a later merge or a new date event).
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.domain.enums import HitOutcome, SearchStatus
from researchpilot.domain.windows import rolling
from researchpilot.services.dates.release_types import classify
from researchpilot.services.dates.releases import load_work_dates
from researchpilot.services.discovery.planner import DiscoveryPlan

DEFAULT_RELEASE_WINDOW_DAYS = 30


async def search_history(session: AsyncSession, run_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        sa.text(
            "SELECT q.id, q.plan_query_id, q.source, q.query_text, q.params, q.origin, "
            "q.rationale, q.status, q.result_count, q.total_available, q.cache_hit, q.error, "
            "q.attempts, q.executed_at, "
            "(SELECT jsonb_object_agg(outcome, n) FROM (SELECT outcome, count(*) AS n "
            " FROM search_results WHERE query_id = q.id GROUP BY outcome) o) AS outcomes "
            "FROM search_queries q WHERE q.run_id = :r "
            "ORDER BY substring(q.plan_query_id FROM 2)::int, q.source"
        ),
        {"r": run_id},
    )
    return [dict(r._mapping) | {"outcomes": r.outcomes or {}} for r in rows]


async def source_report(session: AsyncSession, run_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        sa.text(
            "SELECT source, count(*) AS queries, "
            "count(*) FILTER (WHERE status = 'succeeded') AS succeeded, "
            "count(*) FILTER (WHERE status = 'failed') AS failed, "
            "count(*) FILTER (WHERE status = 'budget_exhausted') AS budget_exhausted, "
            "count(*) FILTER (WHERE status = 'skipped') AS skipped, "
            "count(*) FILTER (WHERE status = 'pending') AS pending, "
            "coalesce(sum(result_count), 0) AS hits, "
            "count(*) FILTER (WHERE cache_hit) AS cache_hits, "
            "(array_agg(error ORDER BY executed_at DESC) FILTER (WHERE error IS NOT NULL))[1] "
            "AS last_error FROM search_queries WHERE run_id = :r GROUP BY source ORDER BY source"
        ),
        {"r": run_id},
    )
    out = []
    for r in rows:
        row = dict(r._mapping)
        if row["succeeded"] == row["queries"]:
            state = "ok"
        elif row["succeeded"]:
            state = "partial"
        elif row["budget_exhausted"]:
            state = "budget_exhausted"
        elif row["pending"] == row["queries"]:
            state = "not_run"
        else:
            state = "unavailable"
        out.append(row | {"state": state})
    return out


async def discovered_papers(
    session: AsyncSession,
    run_id: uuid.UUID,
    plan: DiscoveryPlan,
    now: datetime,
    window_days: int = DEFAULT_RELEASE_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """Each work the run reached (added, already in the project, or a duplicate hit), with the
    searches and sources that found it, the sub-questions those searches serve, its resolved
    date confidence and its release type in the window."""
    rows = (
        await session.execute(
            sa.text(
                "SELECT coalesce(p.merged_into_id, p.id) AS paper_id, r.outcome, r.outcome_detail, "
                "q.plan_query_id, q.source, r.rank FROM search_results r "
                "JOIN search_queries q ON q.id = r.query_id JOIN papers p ON p.id = r.item_id "
                "WHERE q.run_id = :r ORDER BY r.rank"
            ),
            {"r": run_id},
        )
    ).all()
    found: dict[uuid.UUID, dict[str, Any]] = {}
    for r in rows:
        entry = found.setdefault(
            r.paper_id,
            {"queries": set(), "sources": set(), "outcome": None, "flags": [], "best_rank": r.rank},
        )
        entry["queries"].add(r.plan_query_id)
        entry["sources"].add(r.source)
        if r.outcome in (HitOutcome.ADDED.value, HitOutcome.ALREADY_IN_PROJECT.value):
            entry["outcome"] = r.outcome
        if r.outcome_detail and r.outcome_detail.startswith("mentions:"):
            entry["flags"].append(r.outcome_detail.removeprefix("mentions: "))
    if not found:
        return []
    papers = {
        r.id: r
        for r in await session.execute(
            sa.text(
                "SELECT p.id, p.title, p.year, p.date_confidence, p.first_public_appearance, "
                "p.first_public_basis, p.candidate_public_date, pi.objective_version, "
                "pi.discovered_in_run_id, pi.discovered_via FROM papers p "
                "LEFT JOIN project_items pi ON pi.item_id = p.id AND pi.project_id = "
                "(SELECT project_id FROM research_runs WHERE id = :r) WHERE p.id = ANY(:ids)"
            ),
            {"r": run_id, "ids": list(found)},
        )
    }
    window = rolling(now, window_days)
    out = []
    for paper_id, entry in found.items():
        p = papers.get(paper_id)
        if p is None:
            continue
        release = classify(await load_work_dates(session, paper_id), window, now)
        queries = sorted(entry["queries"], key=lambda q: int(q[1:]))
        out.append(
            {
                "paper_id": paper_id,
                "title": p.title,
                "year": p.year,
                "outcome": entry["outcome"] or HitOutcome.DUPLICATE.value,
                "found_by_queries": queries,
                "found_in_sources": sorted(entry["sources"]),
                "sub_question_keys": sorted(
                    {k for k, qs in plan.sub_question_queries.items() if set(qs) & set(queries)}
                ),
                "flags": sorted(set(entry["flags"])),
                "date_confidence": p.date_confidence,
                "first_public_appearance": p.first_public_appearance,
                "first_public_basis": p.first_public_basis,
                "candidate_public_date": p.candidate_public_date,
                "release_type": release.release_type.value if release else None,
                "release_reason": release.reason if release else None,
                "objective_version": p.objective_version,
                "added_by_this_run": p.discovered_in_run_id == run_id,
                "best_rank": entry["best_rank"],
            }
        )
    out.sort(key=lambda x: (x["best_rank"], str(x["title"])))
    return out


async def possible_matches(session: AsyncSession, papers: list[uuid.UUID]) -> list[dict[str, Any]]:
    """Uncertain version matches among the run's works: never merged, waiting for the user."""
    if not papers:
        return []
    rows = await session.execute(
        sa.text(
            "SELECT id, paper_a, paper_b, confidence FROM paper_match_decisions "
            "WHERE outcome = 'possible_match' AND coalesce(user_status, 'pending') = 'pending' "
            "AND (paper_a = ANY(:p) OR paper_b = ANY(:p)) ORDER BY id"
        ),
        {"p": papers},
    )
    return [dict(r._mapping) for r in rows]


async def build_summary(
    session: AsyncSession,
    run_id: uuid.UUID,
    plan: DiscoveryPlan,
    now: datetime,
    citations: dict[str, int] | None = None,
    window_days: int = DEFAULT_RELEASE_WINDOW_DAYS,
) -> dict[str, Any]:
    history = await search_history(session, run_id)
    sources = await source_report(session, run_id)
    papers = await discovered_papers(session, run_id, plan, now, window_days)
    outcomes: Counter[str] = Counter()
    for q in history:
        outcomes.update(q["outcomes"])
    statuses = Counter(q["status"] for q in history)
    coverage: dict[str, dict[str, Any]] = defaultdict(dict)
    for key, query_ids in plan.sub_question_queries.items():
        coverage[key] = {
            "queries": query_ids,
            "papers": sum(1 for p in papers if key in p["sub_question_keys"]),
        }
    merges = await session.execute(
        sa.text(
            "SELECT count(*) FROM paper_merge_events WHERE reverted_at IS NULL AND "
            "surviving_id = ANY(:p)"
        ),
        {"p": [p["paper_id"] for p in papers]},
    )
    matches = await possible_matches(session, [p["paper_id"] for p in papers])
    return {
        "objective_id": str(plan.objective_id),
        "objective_version": plan.objective_version,
        "plan_id": plan.plan_id,
        "planner_version": plan.planner_version,
        "searches": {
            "planned": len(history),
            **{s.value: statuses.get(s.value, 0) for s in SearchStatus},
        },
        "sources": sources,
        "hits": dict(outcomes),
        "papers": {
            "total": len(papers),
            "added": sum(1 for p in papers if p["outcome"] == HitOutcome.ADDED.value),
            "already_in_project": sum(
                1 for p in papers if p["outcome"] == HitOutcome.ALREADY_IN_PROJECT.value
            ),
            "flagged": sum(1 for p in papers if p["flags"]),
        },
        "date_confidence": dict(Counter(str(p["date_confidence"]) for p in papers)),
        "release_window_days": window_days,
        "release_types": dict(
            Counter(p["release_type"] for p in papers if p["release_type"] is not None)
        ),
        "version_matching": {
            "merges": int(merges.scalar_one()),
            "possible_matches_awaiting_review": len(matches),
        },
        "sub_question_coverage": dict(coverage),
        "citations": citations or {},
        "excluded_terms": plan.excluded_terms,
        "not_applied": plan.not_applied,
    }
