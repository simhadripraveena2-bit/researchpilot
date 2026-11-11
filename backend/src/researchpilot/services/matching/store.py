"""Version matching against the database: candidates, decisions, reversible merges (D29).

A merge never deletes or merges manifestations: it re-attaches the merged work's
manifestations - with their identifiers, date events, versions, author lists, version links
and source links - to the surviving work, and records exactly what moved in
``paper_match_decisions`` / ``paper_merge_events``. A split moves the same rows back. The
merged work's row stays (``merged_into_id``), so its graph node and history remain.
User decisions (confirm / reject / split) are sticky.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.core.errors import NotFound, ValidationFailed
from researchpilot.core.ids import uuid7
from researchpilot.domain.enums import (
    DecidedBy,
    MatchOutcome,
    MergeMethod,
    UserMatchStatus,
)
from researchpilot.services.dates.store import resolve_paper_dates
from researchpilot.services.matching.version_matcher import (
    RULE_VERSION,
    Link,
    MatchResult,
    WorkView,
    evaluate,
)

TITLE_CANDIDATE_SIMILARITY = 0.5
MAX_TITLE_CANDIDATES = 20
MAX_MERGES_PER_RUN = 5

# Tables whose rows belong to a manifestation and move with it.
_MANIFESTATION_TABLES = (
    "paper_identifiers",
    "paper_dates",
    "paper_versions",
    "paper_authors",
    "paper_version_links",
    "paper_source_links",
)


@dataclass(frozen=True)
class Decision:
    id: uuid.UUID
    paper_a: uuid.UUID
    paper_b: uuid.UUID
    result: MatchResult
    user_decided: bool


async def load_view(session: AsyncSession, paper_id: uuid.UUID) -> WorkView:
    paper = (
        await session.execute(
            sa.text("SELECT title, publication_type FROM papers WHERE id = :p"), {"p": paper_id}
        )
    ).first()
    if paper is None:
        raise NotFound("paper not found")
    authors_by_m: dict[uuid.UUID, list[str]] = {}
    for row in await session.execute(
        sa.text(
            "SELECT manifestation_id, raw_name FROM paper_authors WHERE paper_id = :p "
            "ORDER BY manifestation_id, position"
        ),
        {"p": paper_id},
    ):
        authors_by_m.setdefault(row.manifestation_id, []).append(row.raw_name)
    authors = max(authors_by_m.values(), key=len, default=[])
    identifiers = frozenset(
        (r.scheme, r.value)
        for r in await session.execute(
            sa.text("SELECT scheme, value FROM paper_identifiers WHERE paper_id = :p"),
            {"p": paper_id},
        )
    )
    links = tuple(
        Link(r.link_type, r.target_scheme, r.target_value, r.source)
        for r in await session.execute(
            sa.text(
                "SELECT link_type, target_scheme, target_value, source "
                "FROM paper_version_links WHERE paper_id = :p"
            ),
            {"p": paper_id},
        )
    )
    kinds = frozenset(
        r.kind
        for r in await session.execute(
            sa.text("SELECT kind FROM paper_manifestations WHERE paper_id = :p"), {"p": paper_id}
        )
    )
    dates = (
        await session.execute(
            sa.text(
                "SELECT min(d.value) FILTER (WHERE m.kind = 'preprint' AND d.event IN "
                "('preprint_posted', 'preprint_announced', 'preprint_submitted') "
                "AND coalesce(d.version, 1) = 1) AS pre, "
                "min(d.value) FILTER (WHERE m.kind <> 'preprint' AND d.event IN "
                "('published_online', 'issue_published', 'issued')) AS pub "
                "FROM paper_dates d JOIN paper_manifestations m "
                "ON m.id = d.manifestation_id WHERE d.paper_id = :p"
            ),
            {"p": paper_id},
        )
    ).one()
    return WorkView(
        paper_id=paper_id,
        title=paper.title,
        authors=tuple(authors),
        identifiers=identifiers,
        links=links,
        manifestation_kinds=kinds,
        publication_type=paper.publication_type,
        earliest_preprint=dates.pre.date() if dates.pre else None,
        earliest_published=dates.pub.date() if dates.pub else None,
    )


async def candidates(session: AsyncSession, paper_id: uuid.UUID) -> list[uuid.UUID]:
    """Works linked by a stated link (either direction) or with a similar title. A similar
    title only makes a pair worth evaluating; it never decides it."""
    rows = await session.execute(
        sa.text(
            "SELECT i.paper_id AS id FROM paper_version_links l JOIN paper_identifiers i "
            "ON i.scheme = l.target_scheme AND i.value = l.target_value WHERE l.paper_id = :p "
            "UNION SELECT l.paper_id FROM paper_version_links l JOIN paper_identifiers i "
            "ON i.scheme = l.target_scheme AND i.value = l.target_value WHERE i.paper_id = :p "
            "UNION (SELECT o.id FROM papers o, papers s WHERE s.id = :p AND o.id <> s.id "
            "AND o.merged_into_id IS NULL "
            "AND similarity(o.normalized_title, s.normalized_title) >= :sim "
            "ORDER BY similarity(o.normalized_title, s.normalized_title) DESC LIMIT :n)"
        ),
        {"p": paper_id, "sim": TITLE_CANDIDATE_SIMILARITY, "n": MAX_TITLE_CANDIDATES},
    )
    found = {r.id for r in rows} - {paper_id}
    if not found:
        return []
    active = await session.execute(
        sa.text("SELECT id FROM papers WHERE id = ANY(:ids) AND merged_into_id IS NULL"),
        {"ids": list(found)},
    )
    return sorted(r.id for r in active)


def _ordered(x: uuid.UUID, y: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    return (x, y) if x < y else (y, x)


async def decide(session: AsyncSession, x: uuid.UUID, y: uuid.UUID) -> Decision:
    a, b = _ordered(x, y)
    user = (
        await session.execute(
            sa.text(
                "SELECT id, outcome, relation, confidence, features FROM "
                "paper_match_decisions WHERE paper_a = :a AND paper_b = :b "
                "AND decided_by = 'user' ORDER BY updated_at DESC LIMIT 1"
            ),
            {"a": a, "b": b},
        )
    ).first()
    view_a, view_b = await load_view(session, a), await load_view(session, b)
    result = evaluate(view_a, view_b)
    if user is not None:  # never overridden by automatic re-matching
        return Decision(user.id, a, b, result, user_decided=True)
    decision_id = (
        await session.execute(
            sa.text(
                "INSERT INTO paper_match_decisions (id, paper_a, paper_b, relation, outcome, "
                "decided_by, user_status, confidence, features, rule_version) VALUES "
                "(:id, :a, :b, :rel, :out, 'system', :us, :c, CAST(:f AS jsonb), :rv) "
                "ON CONFLICT (paper_a, paper_b, rule_version) DO UPDATE SET "
                "relation = excluded.relation, outcome = excluded.outcome, "
                "user_status = excluded.user_status, confidence = excluded.confidence, "
                "features = excluded.features, updated_at = now() RETURNING id"
            ),
            {
                "id": uuid7(),
                "a": a,
                "b": b,
                "rel": result.relation.value,
                "out": result.outcome.value,
                "us": UserMatchStatus.PENDING.value
                if result.outcome is MatchOutcome.POSSIBLE_MATCH
                else None,
                "c": result.confidence,
                "f": json.dumps(result.features),
                "rv": RULE_VERSION,
            },
        )
    ).scalar_one()
    return Decision(decision_id, a, b, result, user_decided=False)


async def match_work(session: AsyncSession, paper_id: uuid.UUID) -> uuid.UUID:
    """Evaluates every candidate pair; auto-matches merge. Returns the surviving work id."""
    current = paper_id
    for _ in range(MAX_MERGES_PER_RUN):
        merged_any = False
        for other in await candidates(session, current):
            decision = await decide(session, current, other)
            if decision.user_decided or not decision.result.merges:
                continue
            survivor, merged = await _survivor(session, current, other)
            await merge(session, survivor, merged, decision.id, _method(decision.result))
            current, merged_any = survivor, True
            break
        if not merged_any:
            return current
    return current


def _method(result: MatchResult) -> MergeMethod:
    if result.features.get("shared_identifiers"):
        return MergeMethod.IDENTIFIER
    if result.features.get("explicit_relation"):
        return MergeMethod.VERSION_RELATION
    return MergeMethod.EVIDENCE_RULES


async def _survivor(
    session: AsyncSession, x: uuid.UUID, y: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    """The older work survives (stable ids for links already shown to users)."""
    rows = (
        await session.execute(
            sa.text("SELECT id FROM papers WHERE id IN (:x, :y) ORDER BY created_at, id"),
            {"x": x, "y": y},
        )
    ).all()
    return rows[0].id, rows[1].id


async def merge(
    session: AsyncSession,
    survivor: uuid.UUID,
    merged: uuid.UUID,
    decision_id: uuid.UUID | None,
    method: MergeMethod,
) -> uuid.UUID:
    if survivor == merged:
        raise ValidationFailed("a work cannot be merged into itself")
    manifestations = [
        str(r.id)
        for r in await session.execute(
            sa.text("SELECT id FROM paper_manifestations WHERE paper_id = :m"), {"m": merged}
        )
    ]
    await _clear_resolution(session, merged)
    for table in _MANIFESTATION_TABLES:
        await session.execute(
            sa.text(f"UPDATE {table} SET paper_id = :s WHERE paper_id = :m"),  # noqa: S608
            {"s": survivor, "m": merged},
        )
    await session.execute(
        sa.text("UPDATE paper_manifestations SET paper_id = :s WHERE paper_id = :m"),
        {"s": survivor, "m": merged},
    )
    moved_projects, dropped = await _move_project_items(session, survivor, merged)
    await session.execute(
        sa.text("UPDATE papers SET merged_into_id = :s WHERE id = :m"),
        {"s": survivor, "m": merged},
    )
    event_id = uuid7()
    await session.execute(
        sa.text(
            "INSERT INTO paper_merge_events (id, surviving_id, merged_id, match_decision_id, "
            "method, moved) VALUES (:id, :s, :m, :d, :method, CAST(:moved AS jsonb))"
        ),
        {
            "id": event_id,
            "s": survivor,
            "m": merged,
            "d": decision_id,
            "method": method.value,
            "moved": json.dumps(
                {
                    "manifestations": manifestations,
                    "project_items_moved": moved_projects,
                    "project_items_dropped": dropped,
                },
                default=str,
            ),
        },
    )
    await resolve_paper_dates(session, survivor, datetime.now(UTC))
    return event_id


async def _move_project_items(
    session: AsyncSession, survivor: uuid.UUID, merged: uuid.UUID
) -> tuple[list[str], list[dict[str, Any]]]:
    """Membership moves to the survivor; where the survivor is already in that project, the
    merged work's row is kept in the merge event (restored by a split)."""
    dropped = [
        dict(r.row)
        for r in await session.execute(
            sa.text(
                "DELETE FROM project_items pi WHERE pi.item_id = :m AND EXISTS ("
                "SELECT 1 FROM project_items s WHERE s.project_id = pi.project_id "
                "AND s.item_id = :s) RETURNING to_jsonb(pi.*) AS row"
            ),
            {"s": survivor, "m": merged},
        )
    ]
    moved = [
        str(r.project_id)
        for r in await session.execute(
            sa.text(
                "UPDATE project_items SET item_id = :s WHERE item_id = :m RETURNING project_id"
            ),
            {"s": survivor, "m": merged},
        )
    ]
    return moved, dropped


async def _clear_resolution(session: AsyncSession, paper_id: uuid.UUID) -> None:
    await session.execute(
        sa.text(
            "UPDATE papers SET first_public_appearance = NULL, first_public_basis = NULL, "
            "first_public_precision = NULL, first_public_manifestation_id = NULL, "
            "first_public_event_id = NULL, candidate_public_date = NULL, "
            "date_confidence = 'uncertain' WHERE id = :p"
        ),
        {"p": paper_id},
    )


async def split(session: AsyncSession, merge_event_id: uuid.UUID, *, by_user: bool) -> None:
    """Undo a merge exactly; a user's split is a sticky rejection of the pair."""
    event = (
        await session.execute(
            sa.text(
                "SELECT surviving_id, merged_id, match_decision_id, moved, reverted_at "
                "FROM paper_merge_events WHERE id = :id FOR UPDATE"
            ),
            {"id": merge_event_id},
        )
    ).first()
    if event is None:
        raise NotFound("merge not found")
    if event.reverted_at is not None:
        raise ValidationFailed("this merge has already been split")
    survivor, merged, moved = event.surviving_id, event.merged_id, event.moved
    manifestations = [uuid.UUID(m) for m in moved["manifestations"]]
    await _clear_resolution(session, survivor)
    for table in _MANIFESTATION_TABLES:
        await session.execute(
            sa.text(
                f"UPDATE {table} SET paper_id = :m "  # noqa: S608
                "WHERE manifestation_id = ANY(:ids)"
            ),
            {"m": merged, "ids": manifestations},
        )
    await session.execute(
        sa.text("UPDATE paper_manifestations SET paper_id = :m WHERE id = ANY(:ids)"),
        {"m": merged, "ids": manifestations},
    )
    for project_id in moved["project_items_moved"]:
        await session.execute(
            sa.text("UPDATE project_items SET item_id = :m WHERE project_id = :p AND item_id = :s"),
            {"m": merged, "s": survivor, "p": uuid.UUID(project_id)},
        )
    for row in moved["project_items_dropped"]:
        await session.execute(
            sa.text(
                "INSERT INTO project_items SELECT * FROM "
                "jsonb_populate_record(NULL::project_items, CAST(:r AS jsonb)) "
                "ON CONFLICT DO NOTHING"
            ),
            {"r": json.dumps(row)},
        )
    await session.execute(
        sa.text("UPDATE papers SET merged_into_id = NULL WHERE id = :m"), {"m": merged}
    )
    await session.execute(
        sa.text("UPDATE paper_merge_events SET reverted_at = now() WHERE id = :id"),
        {"id": merge_event_id},
    )
    if by_user and event.match_decision_id is not None:
        await set_user_decision(session, event.match_decision_id, UserMatchStatus.REJECTED)
    now = datetime.now(UTC)
    await resolve_paper_dates(session, survivor, now)
    await resolve_paper_dates(session, merged, now)


async def set_user_decision(
    session: AsyncSession, decision_id: uuid.UUID, status: UserMatchStatus
) -> None:
    await session.execute(
        sa.text(
            "UPDATE paper_match_decisions SET decided_by = :by, user_status = :s, "
            "updated_at = now() WHERE id = :id"
        ),
        {"by": DecidedBy.USER.value, "s": status.value, "id": decision_id},
    )


async def confirm(session: AsyncSession, decision_id: uuid.UUID) -> uuid.UUID:
    """User confirms a possible match: merge (manual) and keep the decision sticky."""
    row = (
        await session.execute(
            sa.text(
                "SELECT paper_a, paper_b, outcome FROM paper_match_decisions "
                "WHERE id = :id FOR UPDATE"
            ),
            {"id": decision_id},
        )
    ).first()
    if row is None:
        raise NotFound("match decision not found")
    if row.outcome == MatchOutcome.RELATED_NOT_SAME.value:
        raise ValidationFailed("these are related but different works; they cannot be merged")
    await set_user_decision(session, decision_id, UserMatchStatus.CONFIRMED)
    a = await active_work(session, row.paper_a)
    b = await active_work(session, row.paper_b)
    if a == b:
        return a
    survivor, merged = await _survivor(session, a, b)
    await merge(session, survivor, merged, decision_id, MergeMethod.MANUAL)
    return survivor


async def reject(session: AsyncSession, decision_id: uuid.UUID) -> None:
    exists = (
        await session.execute(
            sa.text("SELECT 1 FROM paper_match_decisions WHERE id = :id"), {"id": decision_id}
        )
    ).first()
    if exists is None:
        raise NotFound("match decision not found")
    await set_user_decision(session, decision_id, UserMatchStatus.REJECTED)


async def active_work(session: AsyncSession, paper_id: uuid.UUID) -> uuid.UUID:
    """Follows merged_into_id to the work that currently holds this one."""
    current = paper_id
    for _ in range(10):
        nxt = (
            await session.execute(
                sa.text("SELECT merged_into_id FROM papers WHERE id = :p"), {"p": current}
            )
        ).scalar_one_or_none()
        if nxt is None:
            return current
        current = nxt
    return current
