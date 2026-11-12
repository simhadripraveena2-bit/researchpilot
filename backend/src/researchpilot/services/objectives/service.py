"""Research objective versions in PostgreSQL (DATABASE_SCHEMA §3).

* Every edit creates the next version; earlier versions never change (DB triggers enforce it).
* Optimistic concurrency: an edit names the version it was based on (``base_version``), which
  must still be the project's active version; otherwise ``Conflict`` (409). The project row is
  locked for the duration, and ``UNIQUE(project_id, version)`` is the backstop.
* Sub-questions belong to one version through ``structural_relations`` (``PART_OF``); a new
  version copies them with the same stable keys. New sub-questions get the next key never used
  in the project (SQ1, SQ2, ...), so a removed key is never reused for something else.
* The new version becomes active. Runs and project items record the active version number
  when they are created and keep it (``objective_version``, immutable once set).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.core.errors import Conflict, NotFound, ValidationFailed
from researchpilot.core.ids import uuid7
from researchpilot.db.models import ObjectiveSubQuestion, ResearchObjective
from researchpilot.domain.enums import ExpertiseLevel, ObjectiveSource, ProjectGoal
from researchpilot.events.outbox import emit
from researchpilot.relations.writer import relation_writer
from researchpilot.services.objectives.model import (
    Completeness,
    Constraints,
    ObjectiveContent,
    SubQuestionIn,
    completeness,
    validate,
)

_LIST_FIELDS = (
    "subdomains",
    "target_tasks",
    "problem_areas",
    "focus_concepts",
    "keywords",
    "exclusions",
    "expected_outcomes",
)


class SubQuestionOut(BaseModel):
    id: uuid.UUID
    key: str
    text: str
    ordinal: int


class ObjectiveVersion(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    version: int
    is_active: bool
    core_question: str
    sub_questions: list[SubQuestionOut]
    domain: str | None
    subdomains: list[str]
    target_tasks: list[str]
    problem_areas: list[str]
    focus_concepts: list[str]
    keywords: list[str]
    synonyms: dict[str, list[str]]
    exclusions: list[str]
    constraints: Constraints
    expected_outcomes: list[str]
    user_context: str | None
    notes: str | None
    expertise_level: ExpertiseLevel
    goal: ProjectGoal
    source: ObjectiveSource
    based_on_version: int | None
    change_summary: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    completeness: Completeness

    def content(self) -> ObjectiveContent:
        """This version as editable content (sub-questions keep their keys)."""
        data = self.model_dump(include=set(ObjectiveContent.model_fields) - {"sub_questions"})
        return ObjectiveContent(
            **data,
            sub_questions=[SubQuestionIn(key=s.key, text=s.text) for s in self.sub_questions],
        )


class VersionSummary(BaseModel):
    id: uuid.UUID
    version: int
    is_active: bool
    core_question: str
    source: ObjectiveSource
    based_on_version: int | None
    change_summary: str | None
    created_by: uuid.UUID | None
    created_at: datetime


# --- reads ---------------------------------------------------------------------------------


_PROJECT = "SELECT id, active_objective_id, expertise_level, goal FROM projects WHERE id = :p"


async def _active_id(session: AsyncSession, project_id: uuid.UUID, *, lock: bool) -> Any:
    sql = _PROJECT + " FOR UPDATE" if lock else _PROJECT
    row = (await session.execute(sa.text(sql), {"p": project_id})).one_or_none()
    if row is None:
        raise NotFound("project not found")
    return row


async def _sub_questions(session: AsyncSession, objective_id: uuid.UUID) -> list[SubQuestionOut]:
    rows = (
        await session.execute(
            sa.text(
                "SELECT q.id, q.key, q.text, q.ordinal FROM structural_relations r "
                "JOIN objective_sub_questions q ON q.id = r.child_uid "
                "WHERE r.type = 'PART_OF' AND r.parent_uid = :o AND r.child_kind = 'Topic' "
                "ORDER BY q.ordinal"
            ),
            {"o": objective_id},
        )
    ).mappings()
    return [SubQuestionOut.model_validate(dict(r)) for r in rows]


async def get_objective(
    session: AsyncSession, project_id: uuid.UUID, version: int | None = None
) -> ObjectiveVersion:
    """The given version, or the active one."""
    project = await _active_id(session, project_id, lock=False)
    query = sa.select(ResearchObjective).where(ResearchObjective.project_id == project_id)
    if version is None:
        if project.active_objective_id is None:
            raise NotFound("this project has no research objective yet")
        query = query.where(ResearchObjective.id == project.active_objective_id)
    else:
        query = query.where(ResearchObjective.version == version)
    obj = await session.scalar(query)
    if obj is None:
        raise NotFound(f"objective version {version} not found")
    return await _out(session, obj, project.active_objective_id)


async def _out(
    session: AsyncSession, obj: ResearchObjective, active_id: uuid.UUID | None
) -> ObjectiveVersion:
    out = ObjectiveVersion.model_validate(
        {
            **{c: getattr(obj, c) for c in ObjectiveVersion.model_fields if hasattr(obj, c)},
            "is_active": obj.id == active_id,
            "sub_questions": await _sub_questions(session, obj.id),
            "completeness": Completeness(complete=False, errors=[], missing=[]),
        }
    )
    out.completeness = completeness(out.content())
    return out


async def list_versions(session: AsyncSession, project_id: uuid.UUID) -> list[VersionSummary]:
    project = await _active_id(session, project_id, lock=False)
    rows = (
        await session.scalars(
            sa.select(ResearchObjective)
            .where(ResearchObjective.project_id == project_id)
            .order_by(ResearchObjective.version.desc())
        )
    ).all()
    return [
        VersionSummary.model_validate(
            {
                **{c: getattr(r, c) for c in VersionSummary.model_fields if hasattr(r, c)},
                "is_active": r.id == project.active_objective_id,
            }
        )
        for r in rows
    ]


# --- writes --------------------------------------------------------------------------------


async def create_objective(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID | None,
    content: ObjectiveContent,
    *,
    source: ObjectiveSource = ObjectiveSource.USER_EDIT,
) -> ObjectiveVersion:
    """Version 1. ``Conflict`` if the project already has an objective (edit it instead)."""
    project = await _active_id(session, project_id, lock=True)
    exists = await session.scalar(
        sa.select(sa.func.count())
        .select_from(ResearchObjective)
        .where(ResearchObjective.project_id == project_id)
    )
    if exists:
        raise Conflict("this project already has a research objective; edit it instead")
    if any(s.key is not None for s in content.sub_questions):
        raise ValidationFailed("new sub-questions must not carry keys")
    return await _write_version(
        session, project, user_id, content, version=1, base=None, source=source, summary=None
    )


async def update_objective(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID | None,
    base_version: int,
    content: ObjectiveContent,
    *,
    change_summary: str | None = None,
    source: ObjectiveSource = ObjectiveSource.USER_EDIT,
) -> tuple[ObjectiveVersion, bool]:
    """A new version based on ``base_version`` (the active one). Returns (version, created):
    an edit that changes nothing creates no version."""
    project = await _active_id(session, project_id, lock=True)
    base = await _base(session, project, base_version)
    known = {s.key for s in base.sub_questions}
    unknown = [s.key for s in content.sub_questions if s.key is not None and s.key not in known]
    if unknown:
        raise ValidationFailed(
            f"sub-question {', '.join(unknown)} is not part of version {base_version}"
        )
    content = _with_defaults(content, base.expertise_level, base.goal)
    if content == base.content():
        return base, False
    latest = await session.scalar(
        sa.select(sa.func.max(ResearchObjective.version)).where(
            ResearchObjective.project_id == project_id
        )
    )
    out = await _write_version(
        session,
        project,
        user_id,
        content,
        version=int(latest or 0) + 1,
        base=base_version,
        source=source,
        summary=change_summary,
    )
    return out, True


async def activate_version(
    session: AsyncSession, project_id: uuid.UUID, version: int
) -> ObjectiveVersion:
    """Use an earlier (or later) version again. Nothing is rewritten: runs and items keep the
    version they recorded; new ones use this one."""
    await _active_id(session, project_id, lock=True)
    obj = await session.scalar(
        sa.select(ResearchObjective).where(
            ResearchObjective.project_id == project_id, ResearchObjective.version == version
        )
    )
    if obj is None:
        raise NotFound(f"objective version {version} not found")
    await session.execute(
        sa.text("UPDATE projects SET active_objective_id = :o WHERE id = :p"),
        {"o": obj.id, "p": project_id},
    )
    await emit(session, "objective.activated", project_id=project_id, payload={"version": version})
    return await _out(session, obj, obj.id)


async def edit_sub_questions(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID | None,
    base_version: int,
    *,
    add: str | None = None,
    update: tuple[str, str] | None = None,
    remove: str | None = None,
) -> tuple[ObjectiveVersion, bool]:
    """Add, reword or remove one sub-question; each change is a new version."""
    project = await _active_id(session, project_id, lock=True)
    base = await _base(session, project, base_version)
    sqs = [SubQuestionIn(key=s.key, text=s.text) for s in base.sub_questions]
    keys = {s.key for s in sqs}
    if add is not None:
        sqs.append(SubQuestionIn(text=add))
        summary = "added a sub-question"
    elif update is not None:
        key, text = update
        if key not in keys:
            raise NotFound(f"sub-question {key} not found in version {base_version}")
        sqs = [SubQuestionIn(key=s.key, text=text) if s.key == key else s for s in sqs]
        summary = f"reworded {key}"
    elif remove is not None:
        if remove not in keys:
            raise NotFound(f"sub-question {remove} not found in version {base_version}")
        sqs = [s for s in sqs if s.key != remove]
        summary = f"removed {remove}"
    else:  # pragma: no cover - callers pass exactly one
        raise ValueError("no change")
    content = ObjectiveContent.model_validate(
        {**base.content().model_dump(), "sub_questions": [s.model_dump() for s in sqs]}
    )
    return await update_objective(
        session, project_id, user_id, base_version, content, change_summary=summary
    )


async def _base(session: AsyncSession, project: Any, base_version: int) -> ObjectiveVersion:
    if project.active_objective_id is None:
        raise NotFound("this project has no research objective yet")
    active = await session.get(ResearchObjective, project.active_objective_id)
    assert active is not None
    if active.version != base_version:
        raise Conflict(
            f"the objective changed: version {active.version} is now active "
            f"(your edit was based on version {base_version}); reload and try again",
            active_version=active.version,
        )
    return await _out(session, active, active.id)


def _with_defaults(
    content: ObjectiveContent, level: ExpertiseLevel, goal: ProjectGoal
) -> ObjectiveContent:
    return content.model_copy(
        update={
            "expertise_level": content.expertise_level or level,
            "goal": content.goal or goal,
        }
    )


async def _next_key_number(session: AsyncSession, project_id: uuid.UUID) -> int:
    used = await session.scalar(
        sa.text(
            "SELECT max(substring(q.key FROM 3)::int) FROM research_objectives o "
            "JOIN structural_relations r ON r.parent_uid = o.id AND r.type = 'PART_OF' "
            "JOIN objective_sub_questions q ON q.id = r.child_uid WHERE o.project_id = :p"
        ),
        {"p": project_id},
    )
    return int(used or 0) + 1


async def _write_version(
    session: AsyncSession,
    project: Any,
    user_id: uuid.UUID | None,
    content: ObjectiveContent,
    *,
    version: int,
    base: int | None,
    source: ObjectiveSource,
    summary: str | None,
) -> ObjectiveVersion:
    issues = validate(content)
    if issues:
        raise ValidationFailed(
            "; ".join(f"{i.field}: {i.message}" for i in issues),
            issues=[i.model_dump() for i in issues],
        )
    content = _with_defaults(
        content, ExpertiseLevel(project.expertise_level), ProjectGoal(project.goal)
    )
    obj = ResearchObjective(
        id=uuid7(),
        project_id=project.id,
        version=version,
        core_question=content.core_question,
        domain=content.domain,
        **{f: list(getattr(content, f)) for f in _LIST_FIELDS},
        synonyms=dict(content.synonyms),
        constraints=content.constraints.model_dump(mode="json"),
        user_context=content.user_context or None,
        notes=content.notes or None,
        expertise_level=content.expertise_level,
        goal=content.goal,
        source=source,
        based_on_version=base,
        change_summary=summary,
        created_by=user_id,
    )
    session.add(obj)
    await session.flush()  # registers the Objective graph node
    next_key = await _next_key_number(session, project.id)
    for ordinal, sq in enumerate(content.sub_questions, start=1):
        key = sq.key
        if key is None:
            key, next_key = f"SQ{next_key}", next_key + 1
        child = ObjectiveSubQuestion(id=uuid7(), key=key, text=sq.text, ordinal=ordinal)
        session.add(child)
        await session.flush()
        # Registers the Topic node with the objective's project scope.
        await relation_writer.link_part_of(
            session, project.id, (child.id, "Topic"), (obj.id, "Objective")
        )
    await session.execute(
        sa.text("UPDATE projects SET active_objective_id = :o WHERE id = :p"),
        {"o": obj.id, "p": project.id},
    )
    await emit(
        session,
        "objective.version_created",
        project_id=project.id,
        payload={"version": version, "based_on_version": base},
    )
    return await _out(session, obj, obj.id)


async def active_version_number(session: AsyncSession, project_id: uuid.UUID) -> int | None:
    version: int | None = await session.scalar(
        sa.text(
            "SELECT o.version FROM projects p JOIN research_objectives o "
            "ON o.id = p.active_objective_id WHERE p.id = :p"
        ),
        {"p": project_id},
    )
    return version
