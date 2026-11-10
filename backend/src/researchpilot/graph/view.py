"""Backend-neutral graph response schema (ARCHITECTURE §12.8)."""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class AssertionPolicy(StrEnum):
    ESTABLISHED_ONLY = "established_only"
    INCLUDE_INFERRED = "include_inferred"


class GraphCapability(StrEnum):
    CITATION_GRAPH = "citation_graph"
    PAPER_VERSIONS = "paper_versions"
    NEIGHBORS = "neighbors"
    RELATED_PAPERS = "related_papers"
    PATHS = "paths"
    RICH_EXPLORATION = "rich_exploration"
    GAP_PATTERNS = "gap_patterns"
    CONTRADICTION_ANALYSIS = "contradiction_analysis"
    NOVELTY_NEIGHBORHOOD = "novelty_neighborhood"
    PROVENANCE_TRAIL = "provenance_trail"


# Release in which each capability becomes available (for capability_unavailable errors).
AVAILABLE_FROM: dict[GraphCapability, str] = {
    GraphCapability.CITATION_GRAPH: "R1",
    GraphCapability.PAPER_VERSIONS: "R1",
    GraphCapability.NEIGHBORS: "R1",
    GraphCapability.RELATED_PAPERS: "R1",
    GraphCapability.PATHS: "R2",
    GraphCapability.RICH_EXPLORATION: "R2",
    GraphCapability.GAP_PATTERNS: "R3",
    GraphCapability.CONTRADICTION_ANALYSIS: "R3",
    GraphCapability.NOVELTY_NEIGHBORHOOD: "R3",
    GraphCapability.PROVENANCE_TRAIL: "R4",
}


class GraphNodeView(BaseModel):
    uid: uuid.UUID
    kind: str
    scope: uuid.UUID | None = Field(description="null = global knowledge")
    label: str | None = None


class GraphEdgeView(BaseModel):
    uid: uuid.UUID
    type: str
    source: uuid.UUID
    target: uuid.UUID
    assertion: str
    confidence: float | None = None
    evidence: list[str] = Field(default_factory=list)
    scope: uuid.UUID | None = None


class GraphView(BaseModel):
    nodes: list[GraphNodeView]
    edges: list[GraphEdgeView]
    backend: str
    assertion_policy: AssertionPolicy
