"""Postgres-backed job queue (decision D3: no Redis in the MVP)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from researchpilot.db.base import Base, created_at, enum_type, uuid_pk
from researchpilot.domain.enums import JobStatus


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (sa.Index("ix_jobs_claimable", "status", "run_after"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    status: Mapped[JobStatus] = mapped_column(
        enum_type(JobStatus, "job_status"), nullable=False, server_default=JobStatus.QUEUED.value
    )
    attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    max_attempts: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("3")
    )
    run_after: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    locked_by: Mapped[str | None] = mapped_column(sa.Text)
    locked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Periodic jobs: one job per key (e.g. "arxiv-announcements:2026-11-11").
    dedupe_key: Mapped[str | None] = mapped_column(sa.Text, unique=True)
