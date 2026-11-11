"""Source provenance: raw payloads, HTTP cache and shared rate-limit slots (DATABASE_SCHEMA §4)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from researchpilot.db.base import Base, enum_type, uuid_pk
from researchpilot.domain.enums import SourceName


class SourceRecord(Base):
    """Every raw entity payload we read, stored once per distinct content (R1-3)."""

    __tablename__ = "source_records"
    __table_args__ = (sa.UniqueConstraint("source", "source_entity_id", "payload_sha256"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    source: Mapped[SourceName] = mapped_column(enum_type(SourceName, "source_name"), nullable=False)
    source_entity_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class HttpCacheEntry(Base):
    """Postgres HTTP cache with a TTL per endpoint class (ARCHITECTURE §4.1)."""

    __tablename__ = "http_cache"

    key: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    source: Mapped[SourceName] = mapped_column(enum_type(SourceName, "source_name"), nullable=False)
    url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    headers: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, index=True
    )


class SourceRateLimit(Base):
    """Next free request slot per source, shared by every API and worker process, so the
    combined request rate stays within each provider's limit (R1-4)."""

    __tablename__ = "source_rate_limits"

    source: Mapped[SourceName] = mapped_column(
        enum_type(SourceName, "source_name"), primary_key=True
    )
    next_slot_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
