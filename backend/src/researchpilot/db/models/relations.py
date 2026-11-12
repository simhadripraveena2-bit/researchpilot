"""Relationship sources and their bookkeeping (ARCHITECTURE §12.4-12.6a, DATABASE_SCHEMA §16).

One table (or column) per relationship type; see ``researchpilot.relations.registry``.
Every research relationship row carries the common columns: assertion, confidence,
evidence, provenance, scope, status and row_version. Rows are written only through
``RelationWriter``; database triggers enforce endpoints, scope, evidence and sticky rejection
for any writer (attached in migration 0009 from ``relation_registry``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from researchpilot.db.base import Base, created_at, enum_type, row_version, updated_at, uuid_pk
from researchpilot.domain.enums import (
    Assertion,
    AssertionChangeReason,
    DeletionScope,
    EntityRole,
    ItemType,
    RelationDecisionKind,
    RelationStatus,
    ResearchGroupKind,
    SpanLocation,
    SpanVerification,
    TombstoneReason,
)

_EMPTY_JSON = sa.text("'{}'::jsonb")


def _scope(nullable: bool = True) -> Mapped[uuid.UUID | None]:
    return mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=nullable,
        index=True,
    )


def _assertion() -> Mapped[Assertion]:
    return mapped_column(enum_type(Assertion, "assertion"), nullable=False)


def _confidence() -> Mapped[float | None]:
    return mapped_column(sa.Numeric(4, 3))


def _jsonb() -> Mapped[dict[str, Any]]:
    return mapped_column(JSONB, nullable=False, server_default=_EMPTY_JSON)


def _status() -> Mapped[RelationStatus]:
    return mapped_column(
        enum_type(RelationStatus, "relation_status"),
        nullable=False,
        server_default=RelationStatus.ACTIVE.value,
    )


def _confidence_range() -> sa.CheckConstraint:
    return sa.CheckConstraint(
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"
    )


def _global_only() -> sa.CheckConstraint:
    return sa.CheckConstraint("scope_project_id IS NULL", name="global_only")


def _relation_uid() -> Mapped[uuid.UUID]:
    """Deterministic UUIDv5 edge identity of a composite-key link table (set by trigger)."""
    return mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.FetchedValue()
    )


# --- node sources ----------------------------------------------------------------------


class Author(Base):
    """A resolved author (global node). Raw author lists stay in ``manifestation_authors``."""

    __tablename__ = "authors"

    id: Mapped[uuid.UUID] = uuid_pk()
    display_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    orcid: Mapped[str | None] = mapped_column(sa.Text, unique=True)
    s2_author_id: Mapped[str | None] = mapped_column(sa.Text, unique=True)
    openalex_author_id: Mapped[str | None] = mapped_column(sa.Text, unique=True)
    row_version: Mapped[int] = row_version()
    created_at: Mapped[datetime] = created_at()


class ResearchGroup(Base):
    """An institution, lab or consortium (global node)."""

    __tablename__ = "research_groups"

    id: Mapped[uuid.UUID] = uuid_pk()
    display_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    ror_id: Mapped[str | None] = mapped_column(sa.Text, unique=True)
    openalex_institution_id: Mapped[str | None] = mapped_column(sa.Text, unique=True)
    country: Mapped[str | None] = mapped_column(sa.Text)
    kind: Mapped[ResearchGroupKind] = mapped_column(
        enum_type(ResearchGroupKind, "research_group_kind"),
        nullable=False,
        server_default=ResearchGroupKind.UNKNOWN.value,
    )
    source: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("source_records.id", ondelete="SET NULL")
    )
    row_version: Mapped[int] = row_version()
    created_at: Mapped[datetime] = created_at()


class Entity(Base):
    """Methods, datasets, benchmarks, metrics, models, tasks, concepts (global nodes) and
    glossary terms (not nodes: learning data). The node label follows ``type``."""

    __tablename__ = "entities"
    __table_args__ = (
        sa.UniqueConstraint("type", "canonical_name"),
        sa.CheckConstraint(
            "type NOT IN ('paper', 'repository', 'gap', 'idea')", name="entity_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("research_items.id", ondelete="CASCADE"), primary_key=True
    )
    type: Mapped[ItemType] = mapped_column(enum_type(ItemType, "item_type"), nullable=False)
    canonical_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), server_default=sa.text("'{}'::text[]"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(sa.Text)
    row_version: Mapped[int] = row_version()
    created_at: Mapped[datetime] = created_at()


class EvidenceSpan(Base):
    """A quote from a paper (node data of the paper; referenced by relationship evidence).
    ``document_id`` / ``section_id`` get their foreign keys when documents arrive (M1d)."""

    __tablename__ = "evidence_spans"
    __table_args__ = (
        sa.CheckConstraint(
            "char_start IS NULL OR char_end IS NULL OR char_start <= char_end", name="char_range"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    manifestation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("paper_manifestations.id", ondelete="SET NULL")
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    section_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    location_kind: Mapped[SpanLocation] = mapped_column(
        enum_type(SpanLocation, "span_location"), nullable=False
    )
    page: Mapped[int | None] = mapped_column(sa.Integer)
    char_start: Mapped[int | None] = mapped_column(sa.Integer)
    char_end: Mapped[int | None] = mapped_column(sa.Integer)
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    quote: Mapped[str] = mapped_column(sa.Text, nullable=False)
    verification: Mapped[SpanVerification] = mapped_column(
        enum_type(SpanVerification, "span_verification"), nullable=False
    )
    created_by: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = created_at()


# --- research relationship sources ----------------------------------------------------


class Citation(Base):
    """CITES (Paper -> Paper), global only."""

    __tablename__ = "citations"
    __table_args__ = (_global_only(), _confidence_range())

    citing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    cited_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("papers.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    relation_uid: Mapped[uuid.UUID] = _relation_uid()
    sources: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), server_default=sa.text("'{}'::text[]"), nullable=False
    )
    is_influential: Mapped[bool | None] = mapped_column(sa.Boolean)
    intents: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), server_default=sa.text("'{}'::text[]"), nullable=False
    )
    contexts: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False
    )
    assertion: Mapped[Assertion] = _assertion()
    confidence: Mapped[float | None] = _confidence()
    evidence: Mapped[dict[str, Any]] = _jsonb()
    provenance: Mapped[dict[str, Any]] = _jsonb()
    scope_project_id: Mapped[uuid.UUID | None] = _scope()
    status: Mapped[RelationStatus] = _status()
    row_version: Mapped[int] = row_version()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class PaperAuthor(Base):
    """AUTHORED_BY (Paper -> Author), global only."""

    __tablename__ = "paper_authors"
    __table_args__ = (_global_only(), _confidence_range())

    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("authors.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    relation_uid: Mapped[uuid.UUID] = _relation_uid()
    position: Mapped[int | None] = mapped_column(sa.Integer)
    raw_name: Mapped[str | None] = mapped_column(sa.Text)
    raw_affiliations: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False
    )
    assertion: Mapped[Assertion] = _assertion()
    confidence: Mapped[float | None] = _confidence()
    evidence: Mapped[dict[str, Any]] = _jsonb()
    provenance: Mapped[dict[str, Any]] = _jsonb()
    scope_project_id: Mapped[uuid.UUID | None] = _scope()
    status: Mapped[RelationStatus] = _status()
    row_version: Mapped[int] = row_version()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AuthorAffiliation(Base):
    """AFFILIATED_WITH (Author -> ResearchGroup), global only; ``paper_id`` and ``period``
    are edge properties (natural key: author, group, paper)."""

    __tablename__ = "author_affiliations"
    __table_args__ = (
        _global_only(),
        _confidence_range(),
        sa.Index(
            "uq_author_affiliations_natural_key",
            "author_id",
            "group_id",
            "paper_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("authors.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("research_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("papers.id", ondelete="CASCADE")
    )
    raw_affiliation: Mapped[str | None] = mapped_column(sa.Text)
    period: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    assertion: Mapped[Assertion] = _assertion()
    confidence: Mapped[float | None] = _confidence()
    evidence: Mapped[dict[str, Any]] = _jsonb()
    provenance: Mapped[dict[str, Any]] = _jsonb()
    scope_project_id: Mapped[uuid.UUID | None] = _scope()
    status: Mapped[RelationStatus] = _status()
    row_version: Mapped[int] = row_version()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class EntityLink(Base):
    """INTRODUCES / USES_METHOD / EVALUATES_ON (by ``role``), project or global. The roles
    ``compares_against`` and ``reports_metric`` are assessment data and never projected."""

    __tablename__ = "entity_links"
    __table_args__ = (
        _confidence_range(),
        sa.ForeignKeyConstraint(
            ["subject_uid", "subject_kind"],
            ["graph_nodes.uid", "graph_nodes.kind"],
            name="fk_entity_links_subject_graph_nodes",
            ondelete="CASCADE",
        ),
        sa.Index(
            "uq_entity_links_natural_key",
            "subject_uid",
            "entity_id",
            "role",
            "scope_project_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        # A global row never points at a project's run (no project context in global rows).
        sa.CheckConstraint(
            "scope_project_id IS NOT NULL OR extraction_run_id IS NULL", name="global_no_run"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    subject_uid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    subject_kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[EntityRole] = mapped_column(enum_type(EntityRole, "entity_role"), nullable=False)
    manifestation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("paper_manifestations.id", ondelete="SET NULL")
    )
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("research_runs.id", ondelete="SET NULL")
    )
    assertion: Mapped[Assertion] = _assertion()
    confidence: Mapped[float | None] = _confidence()
    evidence: Mapped[dict[str, Any]] = _jsonb()
    provenance: Mapped[dict[str, Any]] = _jsonb()
    scope_project_id: Mapped[uuid.UUID | None] = _scope()
    status: Mapped[RelationStatus] = _status()
    row_version: Mapped[int] = row_version()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


RESEARCH_RELATION_TYPES = (
    "EXTENDS",
    "CONTRADICTS",
    "RELATED_TO",
    "ADDRESSES",
    "DERIVED_FROM",
    "VALIDATED_BY",
)


class ResearchRelation(Base):
    """The single source of the six research relationship types between any nodes."""

    __tablename__ = "research_relations"
    __table_args__ = (
        sa.CheckConstraint(
            "type IN (" + ", ".join(f"'{t}'" for t in RESEARCH_RELATION_TYPES) + ")",
            name="type",
        ),
        sa.CheckConstraint("assertion <> 'structural'", name="not_structural"),
        _confidence_range(),
        sa.ForeignKeyConstraint(
            ["from_uid", "from_kind"],
            ["graph_nodes.uid", "graph_nodes.kind"],
            name="fk_research_relations_from_graph_nodes",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_uid", "to_kind"],
            ["graph_nodes.uid", "graph_nodes.kind"],
            name="fk_research_relations_to_graph_nodes",
            ondelete="CASCADE",
        ),
        # Natural key: (type, from, to, qualifier, scope); qualifier = properties->>'qualifier'.
        sa.Index(
            "uq_research_relations_natural_key",
            "type",
            "from_uid",
            "to_uid",
            "qualifier",
            "scope_project_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        sa.Index("ix_research_relations_to_uid", "to_uid"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    from_uid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    to_uid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    to_kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    properties: Mapped[dict[str, Any]] = _jsonb()
    # Stored copy of properties->>'qualifier' ('' = none) for the natural key.
    qualifier: Mapped[str] = mapped_column(
        sa.Text,
        sa.Computed("coalesce(properties ->> 'qualifier', '')", persisted=True),
        nullable=False,
    )
    assertion: Mapped[Assertion] = _assertion()
    confidence: Mapped[float | None] = _confidence()
    evidence: Mapped[dict[str, Any]] = _jsonb()
    provenance: Mapped[dict[str, Any]] = _jsonb()
    scope_project_id: Mapped[uuid.UUID | None] = _scope()
    status: Mapped[RelationStatus] = _status()
    row_version: Mapped[int] = row_version()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


# --- decisions, suppressions, assertion history, deletion markers ----------------------


class RelationDecision(Base):
    """A project's decision on a *global* relationship (overlay; the global row is never
    changed). Not a relationship source: no endpoints."""

    __tablename__ = "relation_decisions"
    __table_args__ = (sa.UniqueConstraint("scope_project_id", "relation_uid"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    scope_project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    relation_table: Mapped[str] = mapped_column(sa.Text, nullable=False)
    relation_uid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision: Mapped[RelationDecisionKind] = mapped_column(
        enum_type(RelationDecisionKind, "relation_decision"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(sa.Text)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime] = created_at()


class RelationSuppression(Base):
    """Blocks re-creation of a rejected relationship, also in slightly different form
    (``fingerprint``: hash of type, endpoints and normalised text; no content stored)."""

    __tablename__ = "relation_suppressions"
    __table_args__ = (
        sa.Index(
            "uq_relation_suppressions_key",
            "type",
            "from_uid",
            "to_uid",
            "fingerprint",
            "scope_project_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    from_uid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    to_uid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    fingerprint: Mapped[str] = mapped_column(sa.Text, nullable=False)
    scope_project_id: Mapped[uuid.UUID | None] = _scope()
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()


class RelationAssertionLog(Base):
    """Every change of a relationship's assertion or status (promotion, rejection,
    retraction). Written by trigger. Scoped like the row, so it goes with its project."""

    __tablename__ = "relation_assertion_log"

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    relation_table: Mapped[str] = mapped_column(sa.Text, nullable=False)
    relation_uid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    from_assertion: Mapped[str | None] = mapped_column(sa.Text)
    to_assertion: Mapped[str] = mapped_column(sa.Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(sa.Text)
    to_status: Mapped[str] = mapped_column(sa.Text, nullable=False)
    reason: Mapped[AssertionChangeReason | None] = mapped_column(
        enum_type(AssertionChangeReason, "assertion_change_reason")
    )
    actor: Mapped[str | None] = mapped_column(sa.Text)
    scope_project_id: Mapped[uuid.UUID | None] = _scope()
    created_at: Mapped[datetime] = created_at()


class EntityTombstone(Base):
    """Deletion marker: minimum metadata only (no content, endpoints, project or user IDs)."""

    __tablename__ = "entity_tombstones"

    uid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    reason: Mapped[TombstoneReason] = mapped_column(
        enum_type(TombstoneReason, "tombstone_reason"), nullable=False
    )
    deleted_at: Mapped[datetime] = created_at()
    graph_removed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    verified_absent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")
    purge_after: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now() + interval '30 days'"),
        index=True,
    )


class DeletionLog(Base):
    """Aggregate deletion audit: a one-way salted hash instead of IDs, and counts only."""

    __tablename__ = "deletion_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    subject_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    scope: Mapped[DeletionScope] = mapped_column(
        enum_type(DeletionScope, "deletion_scope"), nullable=False
    )
    object_counts: Mapped[dict[str, Any]] = _jsonb()
    requested_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
