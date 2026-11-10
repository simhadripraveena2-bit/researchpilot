"""R0's PostgreSQL GraphService stays within its documented scope (ARCHITECTURE §12.8)."""

from __future__ import annotations

import uuid

import pytest

from researchpilot.core.errors import CapabilityUnavailable
from researchpilot.graph.adapters.postgres.service import PostgresGraphService
from researchpilot.graph.service import GraphScope
from researchpilot.graph.view import AVAILABLE_FROM, AssertionPolicy, GraphCapability


def _service() -> PostgresGraphService:
    return PostgresGraphService(sessions=None)  # type: ignore[arg-type]  # never queried


def test_r0_advertises_no_capabilities() -> None:
    assert _service().capabilities() == frozenset()


async def test_neighbours_refused_with_r1_availability() -> None:
    with pytest.raises(CapabilityUnavailable) as err:
        await _service().neighbors(
            uuid.uuid4(), GraphScope(uuid.uuid4()), AssertionPolicy.ESTABLISHED_ONLY
        )
    assert err.value.extra == {"capability": "neighbors", "available_from": "R1"}


async def test_paths_refused_with_r2_availability() -> None:
    with pytest.raises(CapabilityUnavailable) as err:
        await _service().paths(
            uuid.uuid4(),
            uuid.uuid4(),
            GraphScope(uuid.uuid4()),
            AssertionPolicy.ESTABLISHED_ONLY,
            3,
        )
    assert err.value.extra["available_from"] == "R2"


def test_availability_table_matches_documented_releases() -> None:
    r1 = {c for c, r in AVAILABLE_FROM.items() if r == "R1"}
    assert r1 == {
        GraphCapability.CITATION_GRAPH,
        GraphCapability.PAPER_VERSIONS,
        GraphCapability.NEIGHBORS,
        GraphCapability.RELATED_PAPERS,
    }
    assert set(AVAILABLE_FROM) == set(GraphCapability)
