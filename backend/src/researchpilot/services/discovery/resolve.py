"""Turn recorded search hits into works in the project (W1 steps 5-11).

For each pending hit, in rank order across queries (so every query contributes):

1. Identifiers: only a DOI or an arXiv ID leads to a system of record; a hit without one is
   recorded as ``no_identifier`` and never becomes a work (nothing is invented).
2. Exclusions: a hit whose title or abstract names an excluded topic is ``excluded``.
3. A work already found in this run is a ``duplicate`` of it.
4. Ingest from the system of record. arXiv and Crossref hits already *are* system-of-record
   records and are stored as returned; Semantic Scholar and OpenAlex hits are resolved to their
   DOI or arXiv record (fetched; arXiv IDs in one batch), then attached as secondary records.
   Existing ingestion resolves dates (the Date Resolver; nothing becomes "verified" unless a
   primary event says so).
5. Follow decisive version links, then the Version Matcher: auto-matches merge (reversibly),
   possible matches are only recorded for the user to decide.
6. IN_PROJECT through RelationWriter, with the run and the run's objective version.

Each hit is one transaction with its outcome, so a resumed run continues exactly where it
stopped, and a failing source only fails its own hits.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import defusedxml.ElementTree as SafeET
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.core.errors import CapabilityUnavailable
from researchpilot.core.logging import get_logger
from researchpilot.db.session import session_scope
from researchpilot.domain.enums import DiscoveredVia, HitOutcome, SourceName
from researchpilot.domain.identifiers import Identifier, IdentifierScheme
from researchpilot.integrations import arxiv, crossref, openalex, semantic_scholar
from researchpilot.integrations.base import SourceError
from researchpilot.integrations.biorxiv import is_server_preprint_doi
from researchpilot.integrations.registry import Sources
from researchpilot.relations.writer import relation_writer
from researchpilot.services.dates.store import resolve_paper_dates
from researchpilot.services.discovery.planner import DiscoveryPlan, matches
from researchpilot.services.discovery.search import system_of_record_ids
from researchpilot.services.matching.store import match_work
from researchpilot.services.papers.enrich import apply_openalex, apply_semantic_scholar
from researchpilot.services.papers.ingest import ingest_arxiv
from researchpilot.services.papers.ingest_crossref import ingest_crossref
from researchpilot.services.papers.service import (
    follow_version_links,
    ingest_identifier,
)

log = get_logger(component="discovery")


@dataclass(frozen=True)
class PendingHit:
    query_id: uuid.UUID
    rank: int
    source: SourceName
    record_id: uuid.UUID | None
    payload: Mapping[str, Any] | None
    fetched_at: datetime | None
    title: str | None
    identifiers: list[Identifier]


@dataclass
class _Parsed:
    abstract: str | None
    arxiv_entry: arxiv.FetchedEntry | None = None
    crossref_work: crossref.FetchedWork | None = None
    s2: semantic_scholar.FetchedS2Paper | None = None
    oa: openalex.FetchedOpenAlexWork | None = None


def _parse(hit: PendingHit) -> _Parsed:
    """Rebuild the hit exactly as the source returned it, from its stored source record."""
    if hit.payload is None or hit.record_id is None or hit.fetched_at is None:
        return _Parsed(None)
    rid, at = hit.record_id, hit.fetched_at
    if hit.source is SourceName.ARXIV_API:
        entry = arxiv.parse_entry(SafeET.fromstring(str(hit.payload["entry_xml"])))
        return _Parsed(entry.abstract, arxiv_entry=arxiv.FetchedEntry(entry, rid, at, False))
    if hit.source is SourceName.CROSSREF:
        work = crossref.parse_work(hit.payload)
        return _Parsed(work.abstract, crossref_work=crossref.FetchedWork(work, rid, at, False))
    if hit.source is SourceName.SEMANTIC_SCHOLAR:
        paper = semantic_scholar.parse_paper(hit.payload)
        s2 = semantic_scholar.FetchedS2Paper(paper, rid, at, False)
        return _Parsed(hit.payload.get("abstract"), s2=s2)
    work_oa = openalex.parse_work(hit.payload)
    oa = openalex.FetchedOpenAlexWork(work_oa, rid, at, False)
    return _Parsed(inverted_abstract(hit.payload.get("abstract_inverted_index")), oa=oa)


def inverted_abstract(index: Any) -> str | None:
    """OpenAlex abstracts come as {word: [positions]}; rebuild the text."""
    if not isinstance(index, dict) or not index:
        return None
    words: dict[int, str] = {}
    for word, positions in index.items():
        for at in positions or []:
            words[int(at)] = str(word)
    return " ".join(words[i] for i in sorted(words))


async def pending_hits(session: AsyncSession, run_id: uuid.UUID) -> list[PendingHit]:
    rows = await session.execute(
        sa.text(
            "SELECT r.query_id, r.rank, q.source, r.source_record_id, sr.payload, sr.fetched_at, "
            "r.title, r.identifiers FROM search_results r "
            "JOIN search_queries q ON q.id = r.query_id "
            "LEFT JOIN source_records sr ON sr.id = r.source_record_id "
            "WHERE q.run_id = :r AND r.outcome = 'pending' "
            "ORDER BY r.rank, substring(q.plan_query_id FROM 2)::int, q.source"
        ),
        {"r": run_id},
    )
    return [
        PendingHit(
            query_id=r.query_id,
            rank=r.rank,
            source=SourceName(r.source),
            record_id=r.source_record_id,
            payload=r.payload,
            fetched_at=r.fetched_at,
            title=r.title,
            identifiers=[
                Identifier(IdentifierScheme(i["scheme"]), i["value"]) for i in r.identifiers
            ],
        )
        for r in rows
    ]


async def _seen(
    session: AsyncSession, run_id: uuid.UUID
) -> tuple[dict[Identifier, uuid.UUID], int]:
    """Works already resolved in this run (for resumption): identifier -> work, and how many
    distinct works count against the candidate limit."""
    rows = await session.execute(
        sa.text(
            "SELECT r.identifiers, r.item_id, r.outcome FROM search_results r "
            "JOIN search_queries q ON q.id = r.query_id WHERE q.run_id = :r "
            "AND r.item_id IS NOT NULL"
        ),
        {"r": run_id},
    )
    seen: dict[Identifier, uuid.UUID] = {}
    works: set[uuid.UUID] = set()
    for r in rows:
        for i in r.identifiers:
            for sor in system_of_record_ids(
                [Identifier(IdentifierScheme(i["scheme"]), i["value"])]
            ):
                seen[sor] = r.item_id
        if r.outcome in (HitOutcome.ADDED.value, HitOutcome.ALREADY_IN_PROJECT.value):
            works.add(r.item_id)
    return seen, len(works)


async def _mark(
    session: AsyncSession,
    hit: PendingHit,
    outcome: HitOutcome,
    item_id: uuid.UUID | None = None,
    detail: str | None = None,
) -> None:
    await session.execute(
        sa.text(
            "UPDATE search_results SET outcome = :o, item_id = :i, outcome_detail = :d, "
            "decided_at = now() WHERE query_id = :q AND rank = :rank"
        ),
        {"o": outcome.value, "i": item_id, "d": detail, "q": hit.query_id, "rank": hit.rank},
    )


async def _survivor(session: AsyncSession, paper_id: uuid.UUID) -> uuid.UUID:
    """The work a (possibly merged) work now lives in."""
    current = paper_id
    for _ in range(10):
        nxt = await session.scalar(
            sa.text("SELECT merged_into_id FROM papers WHERE id = :p"), {"p": current}
        )
        if nxt is None:
            return current
        current = nxt
    return current


async def _known(session: AsyncSession, identifier: Identifier) -> uuid.UUID | None:
    found = await session.scalar(
        sa.text("SELECT paper_id FROM paper_identifiers WHERE scheme = :s AND value = :v"),
        {"s": identifier.scheme.value, "v": identifier.value},
    )
    return None if found is None else await _survivor(session, found)


def _preferred(sor: list[Identifier], source: SourceName) -> Identifier:
    """arXiv hits by their arXiv ID; others by DOI first (as when adding by identifier)."""
    order = (
        (IdentifierScheme.ARXIV, IdentifierScheme.DOI)
        if source is SourceName.ARXIV_API
        else (IdentifierScheme.DOI, IdentifierScheme.ARXIV)
    )
    for scheme in order:
        for i in sor:
            if i.scheme is scheme:
                return i
    return sor[0]


async def _ingest(
    session: AsyncSession,
    sources: Sources,
    hit: PendingHit,
    parsed: _Parsed,
    identifier: Identifier,
    prefetched: dict[str, arxiv.FetchedEntry],
) -> uuid.UUID:
    if parsed.arxiv_entry is not None and identifier.scheme is IdentifierScheme.ARXIV:
        return (await ingest_arxiv(session, parsed.arxiv_entry)).paper_id
    if (
        parsed.crossref_work is not None
        and identifier.scheme is IdentifierScheme.DOI
        and not is_server_preprint_doi(identifier.value)
    ):
        return (await ingest_crossref(session, parsed.crossref_work)).paper_id
    known = await _known(session, identifier)
    if known is not None:
        return known
    if identifier.scheme is IdentifierScheme.ARXIV and identifier.value in prefetched:
        return (await ingest_arxiv(session, prefetched[identifier.value])).paper_id
    return await ingest_identifier(session, sources, identifier)


async def _attach_aggregator(
    session: AsyncSession, paper_id: uuid.UUID, parsed: _Parsed, identifier: Identifier
) -> None:
    if parsed.s2 is None and parsed.oa is None:
        return
    manifestation = await session.scalar(
        sa.text("SELECT manifestation_id FROM paper_identifiers WHERE scheme = :s AND value = :v"),
        {"s": identifier.scheme.value, "v": identifier.value},
    )
    if manifestation is None:
        return
    owner = await session.scalar(
        sa.text("SELECT paper_id FROM paper_manifestations WHERE id = :m"), {"m": manifestation}
    )
    if parsed.s2 is not None:
        await apply_semantic_scholar(session, owner, manifestation, identifier, parsed.s2)
    if parsed.oa is not None:
        await apply_openalex(session, owner, manifestation, identifier, parsed.oa)


async def _prefetch_arxiv(
    sessions: async_sessionmaker[AsyncSession], sources: Sources, hits: list[PendingHit]
) -> dict[str, arxiv.FetchedEntry]:
    """arXiv IDs that only aggregator hits know: one batched request instead of one each."""
    wanted: list[str] = []
    async with session_scope(sessions) as session:
        for hit in hits:
            if hit.source is SourceName.ARXIV_API:
                continue
            sor = system_of_record_ids(hit.identifiers)
            if not sor:
                continue
            ident = _preferred(sor, hit.source)
            if ident.scheme is IdentifierScheme.ARXIV and await _known(session, ident) is None:
                wanted.append(ident.value)
    if not wanted:
        return {}
    try:
        return await sources.arxiv.fetch_many(list(dict.fromkeys(wanted)))
    except SourceError as exc:
        log.warning("discovery.arxiv_batch_failed", detail=exc.detail, count=len(wanted))
        return {}  # each hit then tries on its own and records its failure


async def resolve_hits(
    sessions: async_sessionmaker[AsyncSession],
    sources: Sources,
    run_id: uuid.UUID,
    project_id: uuid.UUID,
    objective_version: int,
    plan: DiscoveryPlan,
    progress: Callable[[str, str], Awaitable[None]],
    ensure_not_cancelled: Callable[[], Awaitable[None]],
) -> None:
    """``ensure_not_cancelled`` (the workflow's ``WorkflowDeps.ensure_not_cancelled``) raises
    ``RunCancelled`` once the run is cancelled. It is checked before the arXiv prefetch and
    before every hit, outside any hit's transaction: hits already decided stay committed,
    the rest stay ``pending`` (resumable), and nothing more is fetched, ingested, matched or
    added to the project."""
    async with session_scope(sessions) as session:
        hits = await pending_hits(session, run_id)
        seen, works = await _seen(session, run_id)
    await ensure_not_cancelled()
    prefetched = await _prefetch_arxiv(sessions, sources, hits)
    for n, hit in enumerate(hits, start=1):
        await ensure_not_cancelled()
        if n % 10 == 1:
            await progress(
                "resolve.progress", f"Checking results {n}-{min(n + 9, len(hits))} of {len(hits)}"
            )
        parsed = _parse(hit)
        sor = system_of_record_ids(hit.identifiers)
        async with session_scope(sessions) as session:
            if not sor:
                await _mark(
                    session,
                    hit,
                    HitOutcome.NO_IDENTIFIER,
                    detail="no DOI or arXiv ID, so no system of record to read it from",
                )
                continue
            excluded = matches(plan.excluded_terms, hit.title, parsed.abstract)
            if excluded:
                await _mark(
                    session,
                    hit,
                    HitOutcome.EXCLUDED,
                    detail=f"mentions excluded topic: {', '.join(excluded)}",
                )
                continue
            already = next((seen[i] for i in sor if i in seen), None)
            if already is not None:
                survivor = await _survivor(session, already)
                await _attach_aggregator(session, survivor, parsed, _preferred(sor, hit.source))
                await _mark(
                    session,
                    hit,
                    HitOutcome.DUPLICATE,
                    survivor,
                    detail="found by an earlier search in this run",
                )
                continue
            if works >= plan.max_candidates:
                await _mark(
                    session,
                    hit,
                    HitOutcome.NOT_PROCESSED,
                    detail=f"beyond the run's limit of {plan.max_candidates} papers",
                )
                continue
        flagged = matches(plan.flagged_terms, hit.title, parsed.abstract)
        identifier = _preferred(sor, hit.source)
        try:
            async with session_scope(sessions) as session:
                paper_id = await _ingest(session, sources, hit, parsed, identifier, prefetched)
                await _attach_aggregator(session, paper_id, parsed, identifier)
                await follow_version_links(session, sources, paper_id)
                survivor = await match_work(session, await _survivor(session, paper_id))
                await resolve_paper_dates(session, survivor, datetime.now(UTC))
                added = await relation_writer.add_to_project(
                    session,
                    project_id,
                    survivor,
                    DiscoveredVia.SEARCH,
                    run_id=run_id,
                    objective_version=objective_version,
                )
                await _mark(
                    session,
                    hit,
                    HitOutcome.ADDED if added else HitOutcome.ALREADY_IN_PROJECT,
                    survivor,
                    detail=f"mentions: {', '.join(flagged)}" if flagged else None,
                )
        except (SourceError, CapabilityUnavailable) as exc:
            async with session_scope(sessions) as session:
                await _mark(session, hit, HitOutcome.FAILED, detail=str(exc.detail)[:500])
            continue
        for i in sor:
            seen[i] = survivor
        works += 1
