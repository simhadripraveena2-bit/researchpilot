"""PostgreSQL GraphService (R0-R1 backend; degraded fallback from R2).

Serves the project's own nodes (``subgraph``) and direct (1-hop) neighbours, read from every
projected relationship source in the registry. Multi-hop paths (R2, Neo4j) are refused with
``capability_unavailable``, never approximated.

Visibility (§12.4.2a): an edge is returned only if its scope is global or the caller's
project and both endpoints are visible to the caller. Rejected and retracted rows are never
returned. The caller's project overlays (``relation_decisions``) apply at query time: a
global edge the project rejected is hidden, one it confirmed is shown as user-confirmed.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.core.errors import GraphCapabilityUnavailable, NotFound
from researchpilot.graph.service import GraphScope
from researchpilot.graph.view import (
    AVAILABLE_FROM,
    AssertionPolicy,
    GraphCapability,
    GraphEdgeView,
    GraphNodeView,
    GraphView,
)
from researchpilot.relations import registry


class PostgresGraphService:
    backend = "postgres"

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    def capabilities(self) -> frozenset[GraphCapability]:
        # Direct neighbours over every relationship source. The citation-graph, version and
        # related-paper views arrive with the discovery workflow that fills those sources.
        return frozenset({GraphCapability.NEIGHBORS})

    def _require(self, capability: GraphCapability) -> None:
        if capability not in self.capabilities():
            raise GraphCapabilityUnavailable(
                f"graph capability {capability.value!r} is not available on the "
                f"{self.backend} backend",
                capability=capability.value,
                available_from=AVAILABLE_FROM[capability],
            )

    async def subgraph(self, scope: GraphScope, policy: AssertionPolicy) -> GraphView:
        async with self._sessions() as session:
            # R0: the project's own nodes (the global layer is empty until R1 adds papers).
            rows = (
                await session.execute(
                    sa.text(
                        "SELECT g.uid, g.kind, g.scope_project_id, p.title FROM graph_nodes g "
                        "LEFT JOIN projects p ON p.id = g.uid WHERE g.scope_project_id = :project "
                        "ORDER BY g.created_at"
                    ),
                    {"project": scope.project_id},
                )
            ).all()
        nodes = [
            GraphNodeView(uid=r.uid, kind=r.kind, scope=r.scope_project_id, label=r.title)
            for r in rows
        ]
        return GraphView(nodes=nodes, edges=[], backend=self.backend, assertion_policy=policy)

    async def neighbors(
        self, uid: uuid.UUID, scope: GraphScope, policy: AssertionPolicy
    ) -> GraphView:
        self._require(GraphCapability.NEIGHBORS)
        async with self._sessions() as session:
            centre = (
                await session.execute(
                    sa.text("SELECT uid, kind, scope_project_id FROM graph_nodes WHERE uid = :u"),
                    {"u": uid},
                )
            ).one_or_none()
            if centre is None or centre.scope_project_id not in (None, scope.project_id):
                raise NotFound("node not found")
            edges = await _edges_touching(session, uid, scope.project_id)
            ids = {uid} | {e["source"] for e in edges} | {e["target"] for e in edges}
            nodes = {
                r.uid: r
                for r in await session.execute(
                    sa.text(
                        "SELECT uid, kind, scope_project_id FROM graph_nodes WHERE uid = ANY(:u)"
                    ),
                    {"u": list(ids)},
                )
            }
        visible = {n for n, r in nodes.items() if r.scope_project_id in (None, scope.project_id)}
        allowed = ESTABLISHED if policy is AssertionPolicy.ESTABLISHED_ONLY else ANY_ACTIVE
        kept = [
            e
            for e in edges
            if e["source"] in visible and e["target"] in visible and e["assertion"] in allowed
        ]
        used = {uid} | {e["source"] for e in kept} | {e["target"] for e in kept}
        return GraphView(
            nodes=[
                GraphNodeView(uid=n, kind=nodes[n].kind, scope=nodes[n].scope_project_id)
                for n in sorted(used, key=str)
            ],
            edges=[GraphEdgeView(**e) for e in kept],
            backend=self.backend,
            assertion_policy=policy,
        )

    async def paths(
        self,
        source: uuid.UUID,
        target: uuid.UUID,
        scope: GraphScope,
        policy: AssertionPolicy,
        max_hops: int,
    ) -> list[GraphView]:
        self._require(GraphCapability.PATHS)
        raise AssertionError("unreachable")  # pragma: no cover


ESTABLISHED = frozenset(
    {
        "source_metadata",
        "author_reported",
        "extracted",
        "computed",
        "user_asserted",
        "user_confirmed",
        "structural",
    }
)
ANY_ACTIVE = ESTABLISHED | {"inferred", "hypothesized"}


async def _edges_touching(
    session: AsyncSession, uid: uuid.UUID, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Active, non-rejected edges at ``uid`` from every projected source, scoped globally or
    to the project, with the project's overlay decisions applied."""
    parts = []
    for spec in registry.AVAILABLE:
        uid_col = "relation_uid" if spec.source_table in _RELATION_UID_TABLES else "id"
        scope = f"t.{spec.scope_column}" if spec.scope_column else "NULL::uuid"
        if spec.is_research:
            extra = "t.assertion, t.confidence, t.status, t.evidence"
        else:
            extra = "'structural' AS assertion, NULL::numeric AS confidence, "
            extra += "'active' AS status, '{}'::jsonb AS evidence"
        where = f"(t.{spec.from_column} = :u OR t.{spec.to_column} = :u)"
        if spec.type_discriminator:
            where += f" AND t.{spec.type_discriminator} = '{spec.discriminator_value}'"
        parts.append(
            f"SELECT t.{uid_col} AS uid, '{spec.type}' AS type, "  # noqa: S608
            f"t.{spec.from_column} AS source, t.{spec.to_column} AS target, {scope} AS scope, "
            f"{extra} FROM {spec.source_table} t WHERE {where}"
        )
    query = (
        "SELECT e.*, d.decision FROM (" + " UNION ALL ".join(parts) + ") e "  # noqa: S608
        "LEFT JOIN relation_decisions d ON d.relation_uid = e.uid AND d.scope_project_id = :p "
        "WHERE (e.scope IS NULL OR e.scope = :p) AND e.status = 'active' "
        "AND e.assertion <> 'rejected' AND d.decision IS DISTINCT FROM 'rejected' "
        "ORDER BY e.type, e.uid"
    )
    rows = (await session.execute(sa.text(query), {"u": uid, "p": project_id})).mappings()
    out = []
    for r in rows:
        evidence = r["evidence"] or {}
        out.append(
            {
                "uid": r["uid"],
                "type": r["type"],
                "source": r["source"],
                "target": r["target"],
                "assertion": "user_confirmed" if r["decision"] == "confirmed" else r["assertion"],
                "confidence": None if r["confidence"] is None else float(r["confidence"]),
                "evidence": [
                    str(i)
                    for k in ("span_ids", "source_record_ids", "signal_ids")
                    for i in evidence.get(k, [])
                ],
                "scope": r["scope"],
            }
        )
    return out


_RELATION_UID_TABLES = frozenset(
    {"citations", "paper_authors", "paper_manifestations", "project_items"}
)
