"""Projects API, readiness, project scope isolation and graph capabilities (R0-2, R0-9, R0-10d)."""

from __future__ import annotations

import httpx
import psycopg
import pytest

from researchpilot.api.app import create_app
from researchpilot.core.ids import uuid7
from researchpilot.core.settings import Settings
from tests.integration.conftest import API, create_project

pytestmark = pytest.mark.integration


async def test_readiness_ok_when_database_reachable(client: httpx.AsyncClient) -> None:
    resp = await client.get(f"{API}/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


async def test_readiness_is_problem_json_503_when_database_unreachable() -> None:
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://nobody:x@127.0.0.1:1/none"
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            resp = await c.get(f"{API}/health/ready")
    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == "dependency_unavailable"


async def test_dependencies_report_configuration_without_secrets(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get(f"{API}/health/dependencies")).json()
    assert body["graph_backend"] == "postgres"
    assert body["llm"] == {"provisional": True, "providers": ["fake"], "forced_fake": True}
    assert all(isinstance(v, bool) for v in body["integrations"].values())


async def test_project_create_read_update_archive(client: httpx.AsyncClient) -> None:
    project_id = await create_project(client)
    got = (await client.get(f"{API}/projects/{project_id}")).json()
    assert got["topic"].startswith("graph neural networks")
    assert got["status"] == "active"

    updated = await client.patch(f"{API}/projects/{project_id}", json={"goal": "find_gap"})
    assert updated.status_code == 200 and updated.json()["goal"] == "find_gap"

    assert (await client.delete(f"{API}/projects/{project_id}")).status_code == 204
    assert (await client.get(f"{API}/projects/{project_id}")).json()["status"] == "archived"
    listed = (await client.get(f"{API}/projects")).json()
    assert project_id in {p["id"] for p in listed}


async def test_invalid_input_is_problem_json(client: httpx.AsyncClient) -> None:
    resp = await client.post(f"{API}/projects", json={"topic": "x", "goal": "nope"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_failed"


async def test_other_users_projects_are_invisible(
    client: httpx.AsyncClient, migrated_db: str
) -> None:
    """A project the caller is not a member of looks exactly like a missing one."""
    other_user, other_project = uuid7(), uuid7()
    with psycopg.connect(migrated_db) as conn:
        conn.execute(
            "INSERT INTO users (id, display_name, auth_provider) VALUES "
            "(%s, 'Someone else', 'password')",
            (other_user,),
        )
        conn.execute(
            "INSERT INTO projects (id, user_id, title, topic, expertise_level, goal) "
            "VALUES (%s, %s, 'Private', 'secret topic', 'advanced', 'find_gap')",
            (other_project, other_user),
        )
        conn.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (%s, %s, 'owner')",
            (other_project, other_user),
        )
        conn.commit()
    for method, path in [
        ("GET", f"/projects/{other_project}"),
        ("PATCH", f"/projects/{other_project}"),
        ("GET", f"/projects/{other_project}/journey"),
        ("GET", f"/projects/{other_project}/graph"),
        ("POST", f"/projects/{other_project}/runs"),
        ("GET", f"/projects/{other_project}/graph/nodes/{other_project}/neighbors"),
    ]:
        body = {"workflow": "dummy"} if method == "POST" else {} if method == "PATCH" else None
        resp = await client.request(method, f"{API}{path}", json=body)
        assert resp.status_code == 404, (method, path, resp.text)
        assert "secret topic" not in resp.text
    assert other_project not in {p["id"] for p in (await client.get(f"{API}/projects")).json()}


async def test_journey_endpoint_returns_nine_stages(client: httpx.AsyncClient) -> None:
    project_id = await create_project(client, goal="find_gap")
    journey = (await client.get(f"{API}/projects/{project_id}/journey")).json()
    assert [s["key"] for s in journey["stages"]][:2] == ["discover", "learn"]
    assert len(journey["stages"]) == 9
    assert journey["next_step"]["stage"] == "discover"


async def test_graph_service_returns_backend_neutral_view(client: httpx.AsyncClient) -> None:
    project_id = await create_project(client)
    view = (await client.get(f"{API}/projects/{project_id}/graph")).json()
    assert view["backend"] == "postgres"
    assert view["assertion_policy"] == "established_only"
    assert [(n["uid"], n["kind"]) for n in view["nodes"]] == [(project_id, "Project")]
    assert view["edges"] == []


async def test_neighbour_traversal_is_unavailable_until_r1(client: httpx.AsyncClient) -> None:
    """Regression: R0 must not advertise or fake direct-neighbour traversal."""
    project_id = await create_project(client)
    resp = await client.get(f"{API}/projects/{project_id}/graph/nodes/{project_id}/neighbors")
    assert resp.status_code == 501
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["code"] == "graph_capability_unavailable"
    assert (body["capability"], body["available_from"]) == ("neighbors", "R1")


async def test_multi_hop_paths_are_unavailable_before_r2(client: httpx.AsyncClient) -> None:
    project_id = await create_project(client)
    resp = await client.get(
        f"{API}/projects/{project_id}/graph/paths",
        params={"source": project_id, "target": project_id},
    )
    assert resp.status_code == 501
    body = resp.json()
    assert body["code"] == "graph_capability_unavailable"
    assert body["available_from"] == "R2"
