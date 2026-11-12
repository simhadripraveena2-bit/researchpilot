"""Versioned research objectives (RIE §2.1, DATABASE_SCHEMA §3).

Every version is immutable: an edit creates the next version, so historical runs,
discoveries and (later) assessments keep pointing at the version they used. Sub-questions
belong to exactly one objective version through ``structural_relations`` (``PART_OF``); the
table deliberately has no ``objective_id`` column (single-source rule, ARCHITECTURE §12.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from researchpilot.db.base import Base, created_at, enum_type, row_version, uuid_pk
from researchpilot.domain.enums import ExpertiseLevel, ObjectiveSource, ProjectGoal

_EMPTY_TEXT_ARRAY = sa.text("'{}'::text[]")


def _texts() -> Mapped[list[str]]:
    return mapped_column(ARRAY(sa.Text), server_default=_EMPTY_TEXT_ARRAY, nullable=False)


class ResearchObjective(Base):
    __tablename__ = "research_objectives"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "version"),
        sa.UniqueConstraint("project_id", "id"),  # target of composite foreign keys
        sa.CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    core_question: Mapped[str] = mapped_column(sa.Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(sa.Text)
    subdomains: Mapped[list[str]] = _texts()
    target_tasks: Mapped[list[str]] = _texts()
    problem_areas: Mapped[list[str]] = _texts()
    focus_concepts: Mapped[list[str]] = _texts()  # must-cover / related concepts
    keywords: Mapped[list[str]] = _texts()
    synonyms: Mapped[dict[str, object]] = mapped_column(  # {term: [synonym, ...]}
        JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
    )
    exclusions: Mapped[list[str]] = _texts()  # out-of-scope topics and methods
    constraints: Mapped[dict[str, object]] = mapped_column(  # methods, data, compute, time...
        JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
    )
    expected_outcomes: Mapped[list[str]] = _texts()
    user_context: Mapped[str | None] = mapped_column(sa.Text)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    expertise_level: Mapped[ExpertiseLevel] = mapped_column(
        enum_type(ExpertiseLevel, "expertise_level"), nullable=False
    )
    goal: Mapped[ProjectGoal] = mapped_column(
        enum_type(ProjectGoal, "project_goal"), nullable=False
    )
    source: Mapped[ObjectiveSource] = mapped_column(
        enum_type(ObjectiveSource, "objective_source"), nullable=False
    )
    based_on_version: Mapped[int | None] = mapped_column(sa.Integer)
    change_summary: Mapped[str | None] = mapped_column(sa.Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    row_version: Mapped[int] = row_version()
    created_at: Mapped[datetime] = created_at()


class ObjectiveSubQuestion(Base):
    """A sub-question of exactly one objective version (``PART_OF`` in structural_relations).
    ``key`` (SQ1, SQ2, ...) is stable across versions and never reused within a project."""

    __tablename__ = "objective_sub_questions"
    __table_args__ = (
        sa.CheckConstraint("key ~ '^SQ[1-9][0-9]*$'", name="key_format"),
        sa.CheckConstraint("ordinal >= 1", name="ordinal_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    row_version: Mapped[int] = row_version()
    created_at: Mapped[datetime] = created_at()
