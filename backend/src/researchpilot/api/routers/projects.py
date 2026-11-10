"""Projects, dashboard, journey and graph views."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Request, Response, status

from researchpilot.api.deps import ProjectScoped, Session, User
from researchpilot.api.schemas import Created, ProjectCreate, ProjectOut, ProjectUpdate
from researchpilot.core.errors import Forbidden
from researchpilot.core.ids import uuid7
from researchpilot.domain.enums import ProjectGoal, ProjectRole
from researchpilot.events.outbox import emit
from researchpilot.graph.service import GraphScope
from researchpilot.graph.view import AssertionPolicy, GraphView
from researchpilot.journey.registry import JourneyView, ProjectStats, compute_journey

router = APIRouter(tags=["projects"])

_COLUMNS = "id, title, topic, expertise_level, goal, status, created_at, updated_at"


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, session: Session, user: User) -> Created:
    project_id = uuid7()
    await session.execute(
        sa.text(
            "INSERT INTO projects (id, user_id, title, topic, expertise_level, goal) "
            "VALUES (:id, :u, :title, :topic, :level, :goal)"
        ),
        {
            "id": project_id,
            "u": user.id,
            "title": body.title or body.topic[:120],
            "topic": body.topic,
            "level": body.expertise_level.value,
            "goal": body.goal.value,
        },
    )
    await session.execute(
        sa.text("INSERT INTO project_members (project_id, user_id, role) VALUES (:p, :u, 'owner')"),
        {"p": project_id, "u": user.id},
    )
    await emit(session, "project.created", project_id=project_id)
    return Created(id=project_id)


@router.get("/projects")
async def list_projects(session: Session, user: User) -> list[ProjectOut]:
    rows = (
        (
            await session.execute(
                sa.text(
                    f"SELECT {', '.join('p.' + c.strip() for c in _COLUMNS.split(','))} "  # noqa: S608
                    "FROM projects p JOIN project_members m ON m.project_id = p.id "
                    "WHERE m.user_id = :u ORDER BY p.updated_at DESC"
                ),
                {"u": user.id},
            )
        )
        .mappings()
        .all()
    )
    return [ProjectOut.model_validate(dict(r)) for r in rows]


@router.get("/dashboard")
async def dashboard(session: Session, user: User) -> dict[str, Any]:
    counts = (
        (
            await session.execute(
                sa.text(
                    "SELECT count(DISTINCT p.id) AS projects, "
                    "count(r.id) FILTER (WHERE r.status IN ('queued','running')) AS active_runs, "
                    "count(r.id) FILTER (WHERE r.status = 'awaiting_approval') "
                    "AS awaiting_approval "
                    "FROM project_members m JOIN projects p ON p.id = m.project_id "
                    "LEFT JOIN research_runs r ON r.project_id = p.id WHERE m.user_id = :u"
                ),
                {"u": user.id},
            )
        )
        .mappings()
        .one()
    )
    return dict(counts)


@router.get("/projects/{project_id}")
async def get_project(scope: ProjectScoped, session: Session) -> ProjectOut:
    row = (
        (
            await session.execute(
                sa.text(f"SELECT {_COLUMNS} FROM projects WHERE id = :id"),  # noqa: S608
                {"id": scope.project_id},
            )
        )
        .mappings()
        .one()
    )
    return ProjectOut.model_validate(dict(row))


@router.patch("/projects/{project_id}")
async def update_project(body: ProjectUpdate, scope: ProjectScoped, session: Session) -> ProjectOut:
    if scope.role is ProjectRole.VIEWER:
        raise Forbidden("viewers cannot change a project")
    changes = {
        k: (v.value if hasattr(v, "value") else v)
        for k, v in body.model_dump(exclude_none=True).items()
    }
    if changes:
        assignments = ", ".join(f"{k} = :{k}" for k in changes)  # keys come from the schema
        await session.execute(
            sa.text(f"UPDATE projects SET {assignments}, updated_at = now() WHERE id = :id"),  # noqa: S608
            {**changes, "id": scope.project_id},
        )
        await emit(
            session,
            "project.updated",
            project_id=scope.project_id,
            payload={"fields": sorted(changes)},
        )
    return await get_project(scope, session)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_project(scope: ProjectScoped, session: Session) -> Response:
    """Archives (soft delete). Permanent deletion arrives with the retention work (R1)."""
    if scope.role is not ProjectRole.OWNER:
        raise Forbidden("only the owner can archive a project")
    await session.execute(
        sa.text("UPDATE projects SET status = 'archived', updated_at = now() WHERE id = :id"),
        {"id": scope.project_id},
    )
    await emit(session, "project.archived", project_id=scope.project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}/journey")
async def journey(scope: ProjectScoped, session: Session) -> JourneyView:
    row = (
        await session.execute(
            sa.text(
                "SELECT goal, (SELECT count(*) FROM research_runs WHERE project_id = :id "
                "AND workflow = 'discovery' "
                "AND status IN ('succeeded','partially_succeeded')) AS d "
                "FROM projects WHERE id = :id"
            ),
            {"id": scope.project_id},
        )
    ).one()
    return compute_journey(ProjectStats(goal=ProjectGoal(row.goal), completed_discovery_runs=row.d))


@router.get("/projects/{project_id}/graph")
async def project_graph(
    scope: ProjectScoped,
    request: Request,
    assertion_policy: AssertionPolicy = AssertionPolicy.ESTABLISHED_ONLY,
) -> GraphView:
    graph = request.app.state.graph
    view: GraphView = await graph.subgraph(GraphScope(scope.project_id), assertion_policy)
    return view
