"""The project's research objective: versions, sub-questions and completeness.

Every change creates a new version (the previous ones are kept and never change); edits name
the version they are based on and get 409 if another edit came first. Viewers can read only.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field, StringConstraints

from researchpilot.api.deps import ProjectScoped, Session
from researchpilot.core.errors import Forbidden
from researchpilot.domain.enums import ProjectRole
from researchpilot.services.objectives import service
from researchpilot.services.objectives.model import Completeness, ObjectiveContent, completeness
from researchpilot.services.objectives.service import ObjectiveVersion, VersionSummary

router = APIRouter(tags=["objective"])

SubQuestionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)
]


class ObjectiveUpdate(ObjectiveContent):
    base_version: int = Field(ge=1, description="the active version this edit is based on")
    change_summary: Annotated[str, StringConstraints(max_length=500)] | None = None


class Activate(BaseModel):
    version: int = Field(ge=1)


class SubQuestionAdd(BaseModel):
    base_version: int = Field(ge=1)
    text: SubQuestionText


class SubQuestionEdit(BaseModel):
    base_version: int = Field(ge=1)
    text: SubQuestionText


def _editor(scope: ProjectScoped) -> None:
    if scope.role is ProjectRole.VIEWER:
        raise Forbidden("viewers cannot change the research objective")


def _created(response: Response, created: bool) -> None:
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK


@router.post("/projects/{project_id}/objective", status_code=status.HTTP_201_CREATED)
async def create_objective(
    body: ObjectiveContent, scope: ProjectScoped, session: Session
) -> ObjectiveVersion:
    """Version 1 of the objective (409 if the project already has one)."""
    _editor(scope)
    return await service.create_objective(session, scope.project_id, scope.user_id, body)


@router.get("/projects/{project_id}/objective")
async def get_objective(
    scope: ProjectScoped,
    session: Session,
    version: Annotated[int | None, Query(ge=1, description="default: the active one")] = None,
) -> ObjectiveVersion:
    return await service.get_objective(session, scope.project_id, version)


@router.put("/projects/{project_id}/objective")
async def update_objective(
    body: ObjectiveUpdate, scope: ProjectScoped, session: Session, response: Response
) -> ObjectiveVersion:
    """Save an edit as a new version (201), or 200 with the active version if nothing
    changed. 409 if ``base_version`` is no longer the active version."""
    _editor(scope)
    content = ObjectiveContent.model_validate(
        body.model_dump(exclude={"base_version", "change_summary"})
    )
    out, created = await service.update_objective(
        session,
        scope.project_id,
        scope.user_id,
        body.base_version,
        content,
        change_summary=body.change_summary,
    )
    _created(response, created)
    return out


@router.get("/projects/{project_id}/objective/versions")
async def list_versions(scope: ProjectScoped, session: Session) -> list[VersionSummary]:
    """All versions, newest first."""
    return await service.list_versions(session, scope.project_id)


@router.post("/projects/{project_id}/objective/active")
async def activate_version(
    body: Activate, scope: ProjectScoped, session: Session
) -> ObjectiveVersion:
    """Make an existing version the active one. New runs and items use it; earlier ones keep
    the version they recorded."""
    _editor(scope)
    return await service.activate_version(session, scope.project_id, body.version)


@router.post("/projects/{project_id}/objective/sub-questions", status_code=status.HTTP_201_CREATED)
async def add_sub_question(
    body: SubQuestionAdd, scope: ProjectScoped, session: Session, response: Response
) -> ObjectiveVersion:
    _editor(scope)
    out, created = await service.edit_sub_questions(
        session, scope.project_id, scope.user_id, body.base_version, add=body.text
    )
    _created(response, created)
    return out


@router.patch("/projects/{project_id}/objective/sub-questions/{key}")
async def update_sub_question(
    key: str, body: SubQuestionEdit, scope: ProjectScoped, session: Session, response: Response
) -> ObjectiveVersion:
    _editor(scope)
    out, created = await service.edit_sub_questions(
        session, scope.project_id, scope.user_id, body.base_version, update=(key, body.text)
    )
    _created(response, created)
    return out


@router.delete("/projects/{project_id}/objective/sub-questions/{key}")
async def remove_sub_question(
    key: str,
    scope: ProjectScoped,
    session: Session,
    response: Response,
    base_version: Annotated[int, Query(ge=1)],
) -> ObjectiveVersion:
    """Removing creates a new version without it; earlier versions still have it."""
    _editor(scope)
    out, created = await service.edit_sub_questions(
        session, scope.project_id, scope.user_id, base_version, remove=key
    )
    _created(response, created)
    return out


@router.post("/projects/{project_id}/objective/validate")
async def validate_objective(body: ObjectiveContent, scope: ProjectScoped) -> Completeness:
    """Check a draft without saving it: errors (cannot be saved) and what is missing."""
    return completeness(body)
