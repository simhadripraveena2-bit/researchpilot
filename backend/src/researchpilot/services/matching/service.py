"""Project-facing match operations: list a work's match decisions, confirm, reject, split."""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.core.errors import NotFound
from researchpilot.services.matching import store


async def _in_project(session: AsyncSession, project_id: uuid.UUID, *papers: uuid.UUID) -> bool:
    active = [await store.active_work(session, p) for p in papers]
    found = (
        await session.execute(
            sa.text("SELECT 1 FROM project_items WHERE project_id = :p AND item_id = ANY(:ids)"),
            {"p": project_id, "ids": active},
        )
    ).first()
    return found is not None


async def list_matches(
    session: AsyncSession, project_id: uuid.UUID, paper_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Every decision involving this work or a work merged into it, newest first."""
    if not await _in_project(session, project_id, paper_id):
        raise NotFound("paper not found in this project")
    rows = (
        (
            await session.execute(
                sa.text(
                    "WITH works AS (SELECT :p AS id UNION SELECT id FROM papers "
                    "WHERE merged_into_id = :p) "
                    "SELECT d.id, d.paper_a, d.paper_b, d.relation, d.outcome, d.decided_by, "
                    "d.user_status, d.confidence, d.features, d.rule_version, d.updated_at, "
                    "(SELECT e.id FROM paper_merge_events e WHERE e.match_decision_id = d.id "
                    "AND e.reverted_at IS NULL ORDER BY e.created_at DESC LIMIT 1) AS merge_id, "
                    "o.id AS other_id, o.title AS other_title, "
                    "o.merged_into_id AS other_merged_into "
                    "FROM paper_match_decisions d JOIN papers o ON o.id = CASE WHEN d.paper_a IN "
                    "(SELECT id FROM works) THEN d.paper_b ELSE d.paper_a END "
                    "WHERE d.paper_a IN (SELECT id FROM works) "
                    "OR d.paper_b IN (SELECT id FROM works) "
                    "ORDER BY d.updated_at DESC"
                ),
                {"p": paper_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def _decision_papers(
    session: AsyncSession, decision_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    row = (
        await session.execute(
            sa.text("SELECT paper_a, paper_b FROM paper_match_decisions WHERE id = :id"),
            {"id": decision_id},
        )
    ).first()
    if row is None:
        raise NotFound("match decision not found")
    return row.paper_a, row.paper_b


async def confirm(
    session: AsyncSession, project_id: uuid.UUID, decision_id: uuid.UUID
) -> uuid.UUID:
    if not await _in_project(session, project_id, *await _decision_papers(session, decision_id)):
        raise NotFound("match decision not found")
    return await store.confirm(session, decision_id)


async def reject(session: AsyncSession, project_id: uuid.UUID, decision_id: uuid.UUID) -> None:
    if not await _in_project(session, project_id, *await _decision_papers(session, decision_id)):
        raise NotFound("match decision not found")
    await store.reject(session, decision_id)


async def split(session: AsyncSession, project_id: uuid.UUID, merge_id: uuid.UUID) -> None:
    row = (
        await session.execute(
            sa.text("SELECT surviving_id, merged_id FROM paper_merge_events WHERE id = :id"),
            {"id": merge_id},
        )
    ).first()
    if row is None or not await _in_project(session, project_id, row.surviving_id):
        raise NotFound("merge not found")
    await store.split(session, merge_id, by_user=True)
