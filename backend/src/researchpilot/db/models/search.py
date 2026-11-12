"""Search log (DATABASE_SCHEMA §4): every query sent and every hit it returned.

A hit is recorded before it becomes a work (``item_id``), and stays recorded when it never
does (no identifier, excluded, failed), so a run's results can always be traced back to the
query, source, time and source record they came from.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from researchpilot.db.base import Base, created_at, enum_type, uuid_pk
from researchpilot.domain.enums import HitOutcome, SearchOrigin, SearchStatus, SourceName


class SearchQuery(Base):
    __tablename__ = "search_queries"
    __table_args__ = (sa.UniqueConstraint("run_id", "plan_query_id", "source"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False
    )
    plan_query_id: Mapped[str] = mapped_column(sa.Text, nullable=False)  # Q1, Q2, ...
    source: Mapped[SourceName] = mapped_column(enum_type(SourceName, "source_name"), nullable=False)
    query_text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    origin: Mapped[SearchOrigin] = mapped_column(
        enum_type(SearchOrigin, "search_origin"), nullable=False
    )
    rationale: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[SearchStatus] = mapped_column(
        enum_type(SearchStatus, "search_status"),
        nullable=False,
        server_default=SearchStatus.PENDING.value,
    )
    result_count: Mapped[int | None] = mapped_column(sa.Integer)
    total_available: Mapped[int | None] = mapped_column(sa.Integer)
    cache_hit: Mapped[bool | None] = mapped_column(sa.Boolean)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")
    executed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class SearchResult(Base):
    __tablename__ = "search_results"
    __table_args__ = (sa.Index("ix_search_results_item_id", "item_id"),)

    query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("search_queries.id", ondelete="CASCADE"),
        primary_key=True,
    )
    rank: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("source_records.id", ondelete="SET NULL")
    )
    source_item_id: Mapped[str] = mapped_column(sa.Text, nullable=False)  # id at the source
    title: Mapped[str | None] = mapped_column(sa.Text)
    identifiers: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("papers.id", ondelete="SET NULL")
    )
    outcome: Mapped[HitOutcome] = mapped_column(
        enum_type(HitOutcome, "hit_outcome"),
        nullable=False,
        server_default=HitOutcome.PENDING.value,
    )
    outcome_detail: Mapped[str | None] = mapped_column(sa.Text)
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
