"""Citation links among discovered works, from the sources' own metadata (W1 step 12).

OpenAlex search hits list the works they cite (``referenced_works``). When a discovered work
cites another work that is already stored (it holds that OpenAlex ID), a CITES relationship
is written through RelationWriter: global (source metadata needs no project context),
assertion ``source_metadata``, evidence = the OpenAlex record, provenance = this workflow.
Nothing is inferred: works we do not hold are not created, and no link is guessed.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.db.session import session_scope
from researchpilot.domain.enums import Assertion
from researchpilot.integrations import openalex
from researchpilot.relations.writer import (
    Evidence,
    NewRelation,
    Outcome,
    Provenance,
    RelationRejected,
    WriteContext,
    relation_writer,
)

SERVICE = "discovery-w1"
SERVICE_VERSION = "1"


async def write_citations(
    sessions: async_sessionmaker[AsyncSession], run_id: uuid.UUID
) -> dict[str, int]:
    counts = {"created": 0, "existing": 0, "suppressed": 0}
    async with session_scope(sessions) as session:
        rows = (
            await session.execute(
                sa.text(
                    "SELECT DISTINCT r.item_id, r.source_record_id, sr.payload "
                    "FROM search_results r JOIN search_queries q ON q.id = r.query_id "
                    "JOIN source_records sr ON sr.id = r.source_record_id "
                    "WHERE q.run_id = :r AND q.source = 'openalex' AND r.item_id IS NOT NULL"
                ),
                {"r": run_id},
            )
        ).all()
    ctx = WriteContext.system(SERVICE)  # global: from source metadata only
    for item_id, record_id, payload in rows:
        refs = openalex.parse_work(payload).referenced_work_ids
        if not refs:
            continue
        async with session_scope(sessions) as session:
            citing = await _survivor(session, item_id)
            cited = await _works_with_openalex_ids(session, list(refs))
            for target in sorted(cited - {citing}, key=str):
                try:
                    result = await relation_writer.write(
                        session,
                        ctx,
                        NewRelation(
                            type="CITES",
                            from_uid=citing,
                            to_uid=target,
                            assertion=Assertion.SOURCE_METADATA,
                            evidence=Evidence(source_record_ids=[record_id]),
                            provenance=Provenance(
                                service=SERVICE,
                                service_version=SERVICE_VERSION,
                                source_api="openalex",
                            ),
                            properties={"sources": ["openalex"]},
                        ),
                    )
                except RelationRejected:
                    continue
                key = {
                    Outcome.CREATED: "created",
                    Outcome.SUPPRESSED: "suppressed",
                }.get(result.outcome, "existing")
                counts[key] += 1
    return counts


async def _survivor(session: AsyncSession, paper_id: uuid.UUID) -> uuid.UUID:
    current = paper_id
    for _ in range(10):
        nxt = await session.scalar(
            sa.text("SELECT merged_into_id FROM papers WHERE id = :p"), {"p": current}
        )
        if nxt is None:
            break
        current = nxt
    return current


async def _works_with_openalex_ids(session: AsyncSession, ids: list[str]) -> set[uuid.UUID]:
    found = await session.execute(
        sa.text(
            "SELECT DISTINCT coalesce(p.merged_into_id, p.id) FROM paper_identifiers i "
            "JOIN papers p ON p.id = i.paper_id WHERE i.scheme = 'openalex' AND i.value = ANY(:v)"
        ),
        {"v": ids},
    )
    return {r[0] for r in found}
