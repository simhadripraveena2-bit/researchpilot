"""Workflow runs, task executions, progress events and human checkpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from researchpilot.db.base import Base, created_at, enum_type, uuid_pk
from researchpilot.domain.enums import CheckpointStatus, RunStatus, TaskStatus, Workflow


class ResearchRun(Base):
    __tablename__ = "research_runs"

    __table_args__ = (
        # The objective version the run used (immutable once set; trigger).
        sa.ForeignKeyConstraint(
            ["project_id", "objective_version"],
            ["research_objectives.project_id", "research_objectives.version"],
            name="fk_research_runs_objective_version",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()  # also the LangGraph thread id
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow: Mapped[Workflow] = mapped_column(enum_type(Workflow, "workflow"), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        enum_type(RunStatus, "run_status"), nullable=False, server_default=RunStatus.QUEUED.value
    )
    config: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    manifest: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    objective_version: Mapped[int | None] = mapped_column(sa.Integer)
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class TaskExecution(Base):
    __tablename__ = "task_executions"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("research_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(enum_type(TaskStatus, "task_status"), nullable=False)
    input_hash: Mapped[str | None] = mapped_column(sa.Text)
    output: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("research_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ts: Mapped[datetime] = created_at()
    level: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="info")
    type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    data: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("research_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    status: Mapped[CheckpointStatus] = mapped_column(
        enum_type(CheckpointStatus, "checkpoint_status"),
        nullable=False,
        server_default=CheckpointStatus.PENDING.value,
    )
    decision: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    comment: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = created_at()
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
