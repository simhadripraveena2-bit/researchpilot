"""Graph-readiness tables (ARCHITECTURE §12, DATABASE_SCHEMA §2 and §16)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from researchpilot.db.base import Base, created_at, enum_type, row_version, uuid_pk
from researchpilot.domain.enums import (
    ItemType,
    OnParentDelete,
    RelationClass,
    ScopePolicy,
    ScopeRule,
)


class ResearchItem(Base):
    """Supertype for everything the Research Intelligence Engine can assess."""

    __tablename__ = "research_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    item_type: Mapped[ItemType] = mapped_column(enum_type(ItemType, "item_type"), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = created_at()


class GraphNode(Base):
    """Node identity registry. Rows are written only by registration triggers."""

    __tablename__ = "graph_nodes"
    __table_args__ = (sa.UniqueConstraint("uid", "kind", name="uq_graph_nodes_uid_kind"),)

    uid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    scope_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = created_at()


class NodeSourceRegistry(Base):
    """The complete node-source inventory (ARCHITECTURE §12.3)."""

    __tablename__ = "node_source_registry"

    source_table: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    label: Mapped[str] = mapped_column(sa.Text, nullable=False)
    registration_condition: Mapped[str | None] = mapped_column(sa.Text)
    scope_rule: Mapped[ScopeRule] = mapped_column(
        enum_type(ScopeRule, "scope_rule"), nullable=False
    )
    scope_column: Mapped[str | None] = mapped_column(sa.Text)
    introduced_in: Mapped[str] = mapped_column(sa.Text, nullable=False)


class RelationRegistry(Base):
    """One row per relationship type -> its single PostgreSQL source (ARCHITECTURE §12.4).
    Drives ``enforce_relation_scope()``."""

    __tablename__ = "relation_registry"

    type: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    relation_class: Mapped[RelationClass] = mapped_column(
        "class", enum_type(RelationClass, "relation_class"), nullable=False
    )
    source_table: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_column: Mapped[str | None] = mapped_column(sa.Text)
    type_discriminator: Mapped[str | None] = mapped_column(sa.Text)
    from_column: Mapped[str] = mapped_column(sa.Text, nullable=False)
    to_column: Mapped[str] = mapped_column(sa.Text, nullable=False)
    scope_column: Mapped[str | None] = mapped_column(sa.Text)
    scope_policy: Mapped[ScopePolicy] = mapped_column(
        enum_type(ScopePolicy, "scope_policy"), nullable=False
    )
    projected: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    required_evidence_policy: Mapped[str] = mapped_column(sa.Text, nullable=False)
    introduced_in: Mapped[str] = mapped_column(sa.Text, nullable=False)


class RelationEndpointRule(Base):
    """Allowed (type, from_kind, to_kind, role) combinations with cardinality and delete rule.
    ``child_table`` names the node source of the child (``from``) endpoint."""

    __tablename__ = "relation_endpoint_rules"

    type: Mapped[str] = mapped_column(
        sa.Text, sa.ForeignKey("relation_registry.type", ondelete="CASCADE"), primary_key=True
    )
    from_kind: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    to_kind: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    role: Mapped[str] = mapped_column(sa.Text, primary_key=True, server_default="")
    child_table: Mapped[str | None] = mapped_column(sa.Text)
    cardinality: Mapped[str] = mapped_column(sa.Text, nullable=False)
    on_parent_delete: Mapped[OnParentDelete] = mapped_column(
        enum_type(OnParentDelete, "on_parent_delete"), nullable=False
    )


class StructuralRelation(Base):
    """The only owner of PART_OF and RESULT_FOR (structural; no evidence)."""

    __tablename__ = "structural_relations"
    __table_args__ = (
        sa.CheckConstraint("type IN ('PART_OF', 'RESULT_FOR')", name="type_allowed"),
        sa.CheckConstraint("assertion = 'structural'", name="assertion_structural"),
        sa.ForeignKeyConstraint(
            ["child_uid", "child_kind"],
            ["graph_nodes.uid", "graph_nodes.kind"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_uid", "parent_kind"],
            ["graph_nodes.uid", "graph_nodes.kind"],
            ondelete="CASCADE",
        ),
        sa.Index(
            "uq_structural_relations_edge",
            "type",
            "child_uid",
            "parent_uid",
            "role",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        sa.Index("ix_structural_relations_parent_uid", "parent_uid"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    child_uid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    child_kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    parent_uid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parent_kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    role: Mapped[str | None] = mapped_column(sa.Text)
    assertion: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="structural")
    scope_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    row_version: Mapped[int] = row_version()
    created_at: Mapped[datetime] = created_at()
