"""Version matching decisions and reversible merges (ARCHITECTURE §4.8a, decision D29)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from researchpilot.db.base import Base, created_at, enum_type, updated_at, uuid_pk
from researchpilot.domain.enums import (
    DecidedBy,
    MatchOutcome,
    MatchRelation,
    MergeMethod,
    SourceName,
    UserMatchStatus,
)
from researchpilot.domain.identifiers import IdentifierScheme


class PaperMatchDecision(Base):
    """One evaluation of a pair of works. ``paper_a < paper_b`` (by id). Decisions made by
    a user are never changed by automatic re-matching (trigger)."""

    __tablename__ = "paper_match_decisions"
    __table_args__ = (
        sa.UniqueConstraint("paper_a", "paper_b", "rule_version"),
        sa.CheckConstraint("paper_a < paper_b", name="ordered_pair"),
        sa.Index("ix_paper_match_decisions_paper_b", "paper_b"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    paper_a: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    paper_b: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[MatchRelation] = mapped_column(
        enum_type(MatchRelation, "match_relation"), nullable=False
    )
    outcome: Mapped[MatchOutcome] = mapped_column(
        enum_type(MatchOutcome, "match_outcome"), nullable=False
    )
    decided_by: Mapped[DecidedBy] = mapped_column(
        enum_type(DecidedBy, "decided_by"), nullable=False
    )
    user_status: Mapped[UserMatchStatus | None] = mapped_column(
        enum_type(UserMatchStatus, "user_match_status")
    )
    confidence: Mapped[Decimal] = mapped_column(sa.Numeric(4, 3), nullable=False)
    features: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    rule_version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class PaperMergeEvent(Base):
    """A merge of ``merged_id`` into ``surviving_id``; ``moved`` lists exactly what moved, so
    a split restores it. Reverted merges keep their row (``reverted_at``)."""

    __tablename__ = "paper_merge_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    surviving_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    merged_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    match_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("paper_match_decisions.id", ondelete="SET NULL")
    )
    method: Mapped[MergeMethod] = mapped_column(
        enum_type(MergeMethod, "merge_method"), nullable=False
    )
    moved: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = created_at()
    reverted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class PaperVersionLink(Base):
    """A version/reply/comment link a source states for one manifestation, extracted from its
    source record (derived index; rebuildable from ``source_records``). Lets the Version
    Matcher find candidate pairs in both directions."""

    __tablename__ = "paper_version_links"
    __table_args__ = (
        sa.UniqueConstraint(
            "manifestation_id", "link_type", "target_scheme", "target_value", "source"
        ),
        sa.Index("ix_paper_version_links_target", "target_scheme", "target_value"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    manifestation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("paper_manifestations.id", ondelete="CASCADE"),
        nullable=False,
    )
    link_type: Mapped[str] = mapped_column(sa.Text, nullable=False)  # e.g. is-preprint-of
    strength: Mapped[str] = mapped_column(sa.Text, nullable=False)  # decisive/strong/related
    target_scheme: Mapped[IdentifierScheme] = mapped_column(
        enum_type(IdentifierScheme, "identifier_scheme"), nullable=False
    )
    target_value: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source: Mapped[SourceName] = mapped_column(enum_type(SourceName, "source_name"), nullable=False)
    evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("source_records.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()
