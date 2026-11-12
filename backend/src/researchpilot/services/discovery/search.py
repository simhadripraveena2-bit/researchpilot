"""Execute planned searches and record them (search_queries / search_results).

Every (planned query, source) pair is one ``search_queries`` row, created when the plan is
stored and updated once the search ran: status, result count, total available, cache hit,
error. Every hit is one ``search_results`` row pointing at the source record that holds the
hit exactly as the source returned it. Nothing here creates works; ``resolve`` does that.

Re-running is safe: queries that already succeeded are not sent again, failed ones are
retried, and hits are recorded once per (query, rank).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.core.ids import uuid7
from researchpilot.core.logging import get_logger
from researchpilot.db.session import session_scope
from researchpilot.domain.enums import HitOutcome, SearchStatus, SourceName
from researchpilot.domain.identifiers import Identifier, IdentifierScheme, arxiv_id_from_doi
from researchpilot.integrations.base import SourceBudgetExhausted, SourceError
from researchpilot.integrations.registry import Sources
from researchpilot.services.discovery.planner import DiscoveryPlan

log = get_logger(component="discovery")

# After this many failed searches in a run, a source is not asked again in that run (its
# remaining queries are recorded as skipped); a resumed run tries it again.
SOURCE_FAILURE_LIMIT = 2


@dataclass(frozen=True)
class Hit:
    rank: int
    source_record_id: uuid.UUID
    source_item_id: str
    title: str | None
    identifiers: list[Identifier]


@dataclass
class SearchOutcome:
    hits: list[Hit] = field(default_factory=list)
    total: int | None = None
    cache_hit: bool | None = None


def _ids(*pairs: tuple[IdentifierScheme, str | None]) -> list[Identifier]:
    out: list[Identifier] = []
    for scheme, value in pairs:
        if value:
            out.append(Identifier(scheme, value))
    return out


def system_of_record_ids(identifiers: list[Identifier]) -> list[Identifier]:
    """DOI and arXiv identifiers only (an arXiv DOI counts as the arXiv ID)."""
    out: list[Identifier] = []
    for i in identifiers:
        if i.scheme is IdentifierScheme.DOI and (arxiv := arxiv_id_from_doi(i.value)):
            out.append(Identifier(IdentifierScheme.ARXIV, arxiv))
        elif i.scheme in (IdentifierScheme.DOI, IdentifierScheme.ARXIV):
            out.append(i)
    return list(dict.fromkeys(out))


async def run_source_query(
    sources: Sources, source: SourceName, text: str, limit: int
) -> SearchOutcome:
    """One search page at one source, normalised to hits with their source records."""
    out = SearchOutcome()
    if source is SourceName.ARXIV_API:
        page = await sources.arxiv.search(text, max_results=limit)
        out.total = page.total
        for rank, f in enumerate(page.entries, start=1):
            e = f.entry
            out.cache_hit = f.cache_hit
            ids = _ids((IdentifierScheme.ARXIV, e.arxiv_id), (IdentifierScheme.DOI, e.doi))
            out.hits.append(Hit(rank, f.source_record_id, e.versioned_id, e.title, ids))
    elif source is SourceName.CROSSREF:
        cr = await sources.crossref.topic_search(text, rows=limit)
        out.total = cr.total_results
        for rank, w in enumerate(cr.works, start=1):
            out.cache_hit = w.cache_hit
            ids = _ids((IdentifierScheme.DOI, w.work.doi))
            out.hits.append(Hit(rank, w.source_record_id, w.work.doi, w.work.title, ids))
    elif source is SourceName.SEMANTIC_SCHOLAR:
        s2 = await sources.semantic_scholar.search(text, limit=limit)
        out.total = s2.total
        for rank, h in enumerate(s2.hits, start=1):
            out.cache_hit = h.cache_hit
            p = h.paper
            out.hits.append(
                Hit(rank, h.source_record_id, p.paper_id, p.title, list(p.listed_identifiers))
            )
    elif source is SourceName.OPENALEX:
        oa = await sources.openalex.search_page(search=text, per_page=limit)
        out.total = oa.total
        for rank, o in enumerate(oa.hits, start=1):
            out.cache_hit = o.cache_hit
            out.hits.append(
                Hit(
                    rank,
                    o.source_record_id,
                    o.work.id,
                    o.work.title,
                    list(o.work.listed_identifiers),
                )
            )
    else:
        raise SourceError(source, f"{source.value} has no topic search")
    return out


async def ensure_queries(session: AsyncSession, run_id: uuid.UUID, plan: DiscoveryPlan) -> None:
    """One search_queries row per (planned query, source); existing rows are kept."""
    for q in plan.queries:
        for source in q.sources:
            await session.execute(
                sa.text(
                    "INSERT INTO search_queries (id, run_id, plan_query_id, source, query_text, "
                    "params, origin, rationale) VALUES (:id, :r, :q, :s, :t, CAST(:p AS jsonb), "
                    ":o, :why) ON CONFLICT (run_id, plan_query_id, source) DO NOTHING"
                ),
                {
                    "id": uuid7(),
                    "r": run_id,
                    "q": q.id,
                    "s": source.value,
                    "t": q.rendered[source.value],
                    "p": json.dumps(
                        {
                            "plain_text": q.text,
                            "purpose": q.purpose,
                            "sub_question_keys": q.sub_question_keys,
                            "max_results": plan.max_results_per_query,
                            "plan_id": plan.plan_id,
                        }
                    ),
                    "o": q.origin.value,
                    "why": q.rationale,
                },
            )


@dataclass(frozen=True)
class QueryRow:
    id: uuid.UUID
    plan_query_id: str
    source: SourceName
    query_text: str


async def queries_to_run(session: AsyncSession, run_id: uuid.UUID) -> list[QueryRow]:
    rows = await session.execute(
        sa.text(
            "SELECT id, plan_query_id, source, query_text FROM search_queries WHERE run_id = :r "
            "AND status <> 'succeeded' ORDER BY substring(plan_query_id FROM 2)::int, source"
        ),
        {"r": run_id},
    )
    return [QueryRow(r.id, r.plan_query_id, SourceName(r.source), r.query_text) for r in rows]


async def execute_searches(
    sessions: async_sessionmaker[AsyncSession],
    sources: Sources,
    run_id: uuid.UUID,
    plan: DiscoveryPlan,
    checkpoint: Callable[[str, str], Awaitable[None]],
    ensure_not_cancelled: Callable[[], Awaitable[None]],
) -> None:
    """Sends every query that has not succeeded yet. One source failing never stops the
    others; each result is committed as soon as it is in (so a crash loses nothing)."""
    async with session_scope(sessions) as session:
        pending = await queries_to_run(session, run_id)
    failures: dict[SourceName, int] = {}
    for row in pending:
        await ensure_not_cancelled()  # before every search: a cancelled run sends nothing more
        if failures.get(row.source, 0) >= SOURCE_FAILURE_LIMIT:
            await _finish_query(
                sessions,
                row.id,
                SearchStatus.SKIPPED,
                error={
                    "reason": f"{row.source.value} failed {SOURCE_FAILURE_LIMIT} times in "
                    "this run; not asked again"
                },
            )
            continue
        await checkpoint(
            "search.started",
            f"Searching {row.source.value.replace('_api', '')}: "
            f"{plan.query(row.plan_query_id).text}",
        )
        try:
            outcome = await run_source_query(
                sources, row.source, row.query_text, plan.max_results_per_query
            )
        except SourceBudgetExhausted as exc:
            failures[row.source] = SOURCE_FAILURE_LIMIT  # no point asking again today
            await _finish_query(sessions, row.id, SearchStatus.BUDGET_EXHAUSTED, error=_error(exc))
            continue
        except SourceError as exc:
            failures[row.source] = failures.get(row.source, 0) + 1
            log.warning("discovery.search_failed", source=row.source.value, detail=exc.detail)
            await _finish_query(sessions, row.id, SearchStatus.FAILED, error=_error(exc))
            continue
        await _finish_query(sessions, row.id, SearchStatus.SUCCEEDED, outcome=outcome)


def _error(exc: SourceError) -> dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "detail": exc.detail,
        "upstream_status": exc.extra.get("upstream_status"),
    }


async def _finish_query(
    sessions: async_sessionmaker[AsyncSession],
    query_id: uuid.UUID,
    status: SearchStatus,
    *,
    outcome: SearchOutcome | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    async with session_scope(sessions) as session:
        await session.execute(
            sa.text(
                "UPDATE search_queries SET status = :s, result_count = :n, total_available = :t, "
                "cache_hit = :c, error = CAST(:e AS jsonb), attempts = attempts + :inc, "
                "executed_at = :at WHERE id = :id"
            ),
            {
                "id": query_id,
                "s": status.value,
                "inc": 0 if status is SearchStatus.SKIPPED else 1,
                "n": len(outcome.hits) if outcome else None,
                "t": outcome.total if outcome else None,
                "c": outcome.cache_hit if outcome else None,
                "e": json.dumps(error) if error else None,
                "at": datetime.now(UTC),
            },
        )
        for hit in outcome.hits if outcome else []:
            await session.execute(
                sa.text(
                    "INSERT INTO search_results (query_id, rank, source_record_id, "
                    "source_item_id, title, identifiers) VALUES (:q, :rank, :rec, :item, :title, "
                    "CAST(:ids AS jsonb)) ON CONFLICT (query_id, rank) DO NOTHING"
                ),
                {
                    "q": query_id,
                    "rank": hit.rank,
                    "rec": hit.source_record_id,
                    "item": hit.source_item_id,
                    "title": hit.title,
                    "ids": json.dumps(
                        [{"scheme": i.scheme.value, "value": i.value} for i in hit.identifiers]
                    ),
                },
            )


__all__ = [
    "SOURCE_FAILURE_LIMIT",
    "HitOutcome",
    "ensure_queries",
    "execute_searches",
    "run_source_query",
    "system_of_record_ids",
]
