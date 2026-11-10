"""Transactional outbox (ARCHITECTURE §4.4)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from researchpilot.db.base import Base, created_at


class DomainEvent(Base):
    __tablename__ = "domain_events"
    __table_args__ = (
        sa.Index(
            "ix_domain_events_unprocessed", "id", postgresql_where=sa.text("processed_at IS NULL")
        ),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_at()
    processed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    last_error: Mapped[str | None] = mapped_column(sa.Text)


class DomainEventDelivery(Base):
    """Per-consumer delivery record, so a retried event never re-runs a consumer that
    already succeeded (idempotent dispatch, R0-4)."""

    __tablename__ = "domain_event_deliveries"

    event_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey("domain_events.id", ondelete="CASCADE"), primary_key=True
    )
    consumer: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    delivered_at: Mapped[datetime] = created_at()
