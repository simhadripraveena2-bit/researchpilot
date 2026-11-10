"""GraphService: the only way agents, services and APIs use the graph (ARCHITECTURE §12.8).

R0 ships the interface and the PostgreSQL implementation skeleton. The Neo4j implementation
arrives in R2 (``graph/adapters/neo4j``), behind the same interface.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from researchpilot.graph.view import AssertionPolicy, GraphCapability, GraphView


@dataclass(frozen=True)
class GraphScope:
    """What the caller may see: global knowledge plus one project."""

    project_id: uuid.UUID


class GraphService(Protocol):
    backend: str

    def capabilities(self) -> frozenset[GraphCapability]: ...

    async def subgraph(self, scope: GraphScope, policy: AssertionPolicy) -> GraphView: ...

    async def neighbors(
        self, uid: uuid.UUID, scope: GraphScope, policy: AssertionPolicy
    ) -> GraphView: ...

    async def paths(
        self,
        source: uuid.UUID,
        target: uuid.UUID,
        scope: GraphScope,
        policy: AssertionPolicy,
        max_hops: int,
    ) -> list[GraphView]: ...
