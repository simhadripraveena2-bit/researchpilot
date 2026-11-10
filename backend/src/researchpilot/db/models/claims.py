"""Typed claims and their evidence/verification (DATABASE_SCHEMA §7).

``claim_evidence.evidence_span_id`` and ``signal_id`` get their foreign keys in R1, when
``evidence_spans`` and ``assessment_signals`` are created.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from researchpilot.db.base import Base, created_at, enum_type, uuid_pk
from researchpilot.domain.enums import (
    ClaimKind,
    ClaimOrigin,
    ClaimStatus,
    EvidenceRelation,
    Grounding,
    VerificationLevel,
    VerificationResult,
)


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        sa.CheckConstraint(
            "(kind = 'ai_interpretation') = (grounding IS NOT NULL)", name="grounding_iff_ai"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ClaimKind] = mapped_column(enum_type(ClaimKind, "claim_kind"), nullable=False)
    grounding: Mapped[Grounding | None] = mapped_column(enum_type(Grounding, "grounding"))
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_by: Mapped[str] = mapped_column(sa.Text, nullable=False)
    origin_type: Mapped[ClaimOrigin] = mapped_column(
        enum_type(ClaimOrigin, "claim_origin"), nullable=False
    )
    origin_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[ClaimStatus] = mapped_column(
        enum_type(ClaimStatus, "claim_status"),
        nullable=False,
        server_default=ClaimStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = created_at()


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (
        sa.CheckConstraint(
            "num_nonnulls(evidence_span_id, item_id, signal_id) >= 1", name="has_reference"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_span_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("research_items.id", ondelete="CASCADE")
    )
    signal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    relation: Mapped[EvidenceRelation] = mapped_column(
        enum_type(EvidenceRelation, "evidence_relation"), nullable=False
    )


class ClaimVerification(Base):
    __tablename__ = "claim_verifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    level: Mapped[VerificationLevel] = mapped_column(
        enum_type(VerificationLevel, "verification_level"), nullable=False
    )
    result: Mapped[VerificationResult] = mapped_column(
        enum_type(VerificationResult, "verification_result"), nullable=False
    )
    details: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    checked_at: Mapped[datetime] = created_at()
