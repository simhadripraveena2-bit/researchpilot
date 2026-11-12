"""Permanent project deletion (ARCHITECTURE §12.6a, S7).

Deleting the project row cascades to everything project-scoped: objectives and
sub-questions, runs, items, scoped relationships (including project-scoped assertions about
global nodes), decisions, suppressions and the assertion log. Database triggers write a
deletion marker (reason ``project_delete``) for every graph node and edge removed. Global
knowledge (papers, authors, global relationships) is not personal content and stays. The
audit log keeps only a one-way hash of the project id and counts.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.core.ids import uuid7
from researchpilot.domain.enums import DeletionScope
from researchpilot.relations import registry


def subject_hash(subject_id: uuid.UUID, salt: str | None) -> str:
    """HMAC-SHA256 of the id. Without a configured salt a random one is used and discarded,
    so the entry cannot be linked to the project at all."""
    key = (salt or secrets.token_hex(32)).encode()
    return hmac.new(key, str(subject_id).encode(), hashlib.sha256).hexdigest()


async def _counts(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    async def count(sql: str) -> int:
        return int(await session.scalar(sa.text(sql), {"p": project_id}) or 0)

    relationships = {}
    for table in sorted({s.source_table for s in registry.AVAILABLE if s.scope_column}):
        column = next(
            s.scope_column for s in registry.AVAILABLE if s.source_table == table and s.scope_column
        )
        relationships[table] = await count(
            f"SELECT count(*) FROM {table} WHERE {column} = :p"  # noqa: S608
        )
    return {
        "graph_nodes": await count("SELECT count(*) FROM graph_nodes WHERE scope_project_id = :p"),
        "relationships": relationships,
        "objective_versions": await count(
            "SELECT count(*) FROM research_objectives WHERE project_id = :p"
        ),
        "runs": await count("SELECT count(*) FROM research_runs WHERE project_id = :p"),
        "relation_decisions": await count(
            "SELECT count(*) FROM relation_decisions WHERE scope_project_id = :p"
        ),
    }


async def delete_project(
    session: AsyncSession, project_id: uuid.UUID, *, salt: str | None, requested_at: datetime
) -> dict[str, Any]:
    counts = await _counts(session, project_id)
    await session.execute(
        sa.text("SELECT set_config('rp.deletion_reason', 'project_delete', true)")
    )
    # Outbox events can carry project details in their payloads.
    await session.execute(
        sa.text("DELETE FROM domain_events WHERE project_id = :p"), {"p": project_id}
    )
    await session.execute(sa.text("DELETE FROM projects WHERE id = :p"), {"p": project_id})
    await session.execute(sa.text("SELECT set_config('rp.deletion_reason', '', true)"))
    await session.execute(
        sa.text(
            "INSERT INTO deletion_log (id, subject_hash, scope, object_counts, requested_at, "
            "completed_at) VALUES (:id, :h, :s, CAST(:c AS jsonb), :r, now())"
        ),
        {
            "id": uuid7(),
            "h": subject_hash(project_id, salt),
            "s": DeletionScope.PROJECT.value,
            "c": json.dumps(counts),
            "r": requested_at,
        },
    )
    return counts
