"""PostgreSQL GraphService (R0-R1 backend; degraded fallback from R2).

R0 has no relationship tables yet: it serves only the project's own nodes (``subgraph``) and
advertises no capabilities. Neighbour traversal (R1) and multi-hop paths (R2, Neo4j) are
refused with ``capability_unavailable``, never approximated.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.core.errors import CapabilityUnavailable
from researchpilot.graph.service import GraphScope
from researchpilot.graph.view import (
    AVAILABLE_FROM,
    AssertionPolicy,
    GraphCapability,
    GraphNodeView,
    GraphView,
)


class PostgresGraphService:
    backend = "postgres"

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    def capabilities(self) -> frozenset[GraphCapability]:
        # R0 advertises nothing: only the project subgraph view exists. R1 adds the citation
        # graph, paper versions, direct (1-hop) neighbours and basic related papers.
        return frozenset()

    def _require(self, capability: GraphCapability) -> None:
        if capability not in self.capabilities():
            raise CapabilityUnavailable(
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
        """Direct-neighbour traversal is an R1 capability (no relationship sources exist in R0)."""
        self._require(GraphCapability.NEIGHBORS)
        raise AssertionError("unreachable")  # pragma: no cover

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
