"""Request dependencies: database session, current user and project scope (S2).

Every project-scoped route must depend on one of the resolvers in ``SCOPE_RESOLVERS``; a
route-inventory test enforces this (R0-9). Resolution checks membership and returns 404 for
projects the user cannot see, so other projects' existence is not revealed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.core.errors import NotFound
from researchpilot.core.ids import uuid7
from researchpilot.core.settings import Settings
from researchpilot.domain.enums import ProjectRole


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One transaction per request: committed on success, rolled back on error."""
    sessions: async_sessionmaker[AsyncSession] = request.app.state.sessions
    async with sessions() as session, session.begin():
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID


async def current_user(session: Session) -> CurrentUser:
    """AUTH_MODE=disabled: the single implicit local user (created on first use).

    Hosted authentication (gate H) replaces this dependency; the app refuses to start with any
    other auth mode until then.
    """
    await session.execute(
        sa.text(
            "INSERT INTO users (id, display_name, auth_provider) "
            "VALUES (:id, 'Local user', 'local_none') "
            "ON CONFLICT (auth_provider) WHERE auth_provider = 'local_none' DO NOTHING"
        ),
        {"id": uuid7()},
    )
    user_id = (
        await session.execute(sa.text("SELECT id FROM users WHERE auth_provider = 'local_none'"))
    ).scalar_one()
    return CurrentUser(id=user_id)


User = Annotated[CurrentUser, Depends(current_user)]


@dataclass(frozen=True)
class ProjectScope:
    project_id: uuid.UUID
    user_id: uuid.UUID
    role: ProjectRole


async def _scope(session: AsyncSession, user: CurrentUser, project_id: uuid.UUID) -> ProjectScope:
    role = (
        await session.execute(
            sa.text(
                "SELECT m.role FROM project_members m JOIN projects p ON p.id = m.project_id "
                "WHERE m.project_id = :p AND m.user_id = :u"
            ),
            {"p": project_id, "u": user.id},
        )
    ).scalar_one_or_none()
    if role is None:
        raise NotFound("project not found")
    return ProjectScope(project_id=project_id, user_id=user.id, role=ProjectRole(role))


async def scope_from_project(project_id: uuid.UUID, session: Session, user: User) -> ProjectScope:
    return await _scope(session, user, project_id)


async def scope_from_run(run_id: uuid.UUID, session: Session, user: User) -> ProjectScope:
    project_id = (
        await session.execute(
            sa.text("SELECT project_id FROM research_runs WHERE id = :id"), {"id": run_id}
        )
    ).scalar_one_or_none()
    if project_id is None:
        raise NotFound("run not found")
    return await _scope(session, user, project_id)


async def scope_from_checkpoint(
    checkpoint_id: uuid.UUID, session: Session, user: User
) -> ProjectScope:
    project_id = (
        await session.execute(
            sa.text(
                "SELECT r.project_id FROM checkpoints c JOIN research_runs r ON r.id = c.run_id "
                "WHERE c.id = :id"
            ),
            {"id": checkpoint_id},
        )
    ).scalar_one_or_none()
    if project_id is None:
        raise NotFound("checkpoint not found")
    return await _scope(session, user, project_id)


SCOPE_RESOLVERS = (scope_from_project, scope_from_run, scope_from_checkpoint)

ProjectScoped = Annotated[ProjectScope, Depends(scope_from_project)]
RunScoped = Annotated[ProjectScope, Depends(scope_from_run)]
CheckpointScoped = Annotated[ProjectScope, Depends(scope_from_checkpoint)]
