"""Graph-readiness tables (ARCHITECTURE §12, DATABASE_SCHEMA §2 and §16)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from researchpilot.db.base import Base, created_at, enum_type, uuid_pk
from researchpilot.domain.enums import ItemType, ScopeRule


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
