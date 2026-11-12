"""Users, projects and project membership (DATABASE_SCHEMA §3)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from researchpilot.db.base import Base, created_at, enum_type, row_version, updated_at, uuid_pk
from researchpilot.domain.enums import (
    AuthProvider,
    ExpertiseLevel,
    ProjectGoal,
    ProjectRole,
    ProjectStatus,
    TimezoneSource,
    TutorRetentionPolicy,
)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # At most one implicit local user (AUTH_MODE=disabled), even under concurrent requests.
        sa.Index(
            "uq_users_single_local",
            "auth_provider",
            unique=True,
            postgresql_where=sa.text("auth_provider = 'local_none'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    display_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    email: Mapped[str | None] = mapped_column(sa.Text, unique=True)
    auth_provider: Mapped[AuthProvider] = mapped_column(
        enum_type(AuthProvider, "auth_provider"),
        nullable=False,
        server_default=AuthProvider.LOCAL_NONE.value,
    )
    auth_subject: Mapped[str | None] = mapped_column(sa.Text)
    password_hash: Mapped[str | None] = mapped_column(sa.Text)
    mfa_enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    default_level: Mapped[ExpertiseLevel] = mapped_column(
        enum_type(ExpertiseLevel, "expertise_level"),
        nullable=False,
        server_default=ExpertiseLevel.BEGINNER.value,
    )
    timezone: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="UTC")
    timezone_source: Mapped[TimezoneSource] = mapped_column(
        enum_type(TimezoneSource, "timezone_source"),
        nullable=False,
        server_default=TimezoneSource.BROWSER.value,
    )
    preferences: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_at()
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        sa.CheckConstraint(
            "(tutor_retention_policy = 'delete_after_days') = (tutor_retention_days IS NOT NULL)",
            name="retention_days_iff_policy",
        ),
        # The active version must be one of this project's objective versions.
        sa.ForeignKeyConstraint(
            ["id", "active_objective_id"],
            ["research_objectives.project_id", "research_objectives.id"],
            name="fk_projects_active_objective",
            use_alter=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(  # owner (DATABASE_SCHEMA §3)
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    topic: Mapped[str] = mapped_column(sa.Text, nullable=False)
    expertise_level: Mapped[ExpertiseLevel] = mapped_column(
        enum_type(ExpertiseLevel, "expertise_level"), nullable=False
    )
    goal: Mapped[ProjectGoal] = mapped_column(
        enum_type(ProjectGoal, "project_goal"), nullable=False
    )
    settings: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    tutor_retention_policy: Mapped[TutorRetentionPolicy] = mapped_column(
        enum_type(TutorRetentionPolicy, "tutor_retention_policy"),
        nullable=False,
        server_default=TutorRetentionPolicy.KEEP_UNTIL_DELETED.value,
    )
    tutor_retention_days: Mapped[int | None] = mapped_column(sa.Integer)
    # The objective version currently in use (any version of this project's objective).
    active_objective_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[ProjectStatus] = mapped_column(
        enum_type(ProjectStatus, "project_status"),
        nullable=False,
        server_default=ProjectStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    row_version: Mapped[int] = row_version()


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[ProjectRole] = mapped_column(
        enum_type(ProjectRole, "project_role"), nullable=False
    )
    added_at: Mapped[datetime] = created_at()
