"""Research objective model: versions, sub-questions, authorization, concurrency, and the
objective version recorded by runs and project items."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from psycopg import errors
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.core.errors import Conflict
from researchpilot.core.ids import uuid7
from researchpilot.services.objectives import service
from researchpilot.services.objectives.model import ObjectiveContent
from tests.integration.conftest import API, create_project

pytestmark = pytest.mark.integration

DRAFT: dict[str, Any] = {
    "core_question": "Which GNN architectures predict molecular properties best?",
    "sub_questions": [
        {"text": "Which benchmarks are used?"},
        {"text": "How do message passing and graph transformers compare?"},
    ],
    "domain": "machine learning",
    "subdomains": ["graph learning"],
    "target_tasks": ["molecular property prediction"],
    "problem_areas": ["small labelled datasets"],
    "focus_concepts": ["message passing"],
    "keywords": ["GNN", "molecular graphs"],
    "synonyms": {"GNN": ["graph neural network"]},
    "exclusions": ["protein folding"],
    "constraints": {
        "methods": {"preferred": ["GNN"], "avoided": ["LLM fine-tuning"]},
        "datasets": {"required": ["QM9"], "open_access_only": True},
        "benchmarks": {"preferred": ["MoleculeNet"]},
        "compute": {"gpu_hours": 100, "hardware": ["one A100"]},
        "time": {"horizon": "3 months"},
        "resources": ["one PhD student"],
    },
    "expected_outcomes": ["a ranked shortlist of methods"],
    "user_context": "Pharma lab, applied focus.",
    "notes": "Prefer work since 2020.",
}


def objective_url(project_id: str) -> str:
    return f"{API}/projects/{project_id}/objective"


async def create(client: httpx.AsyncClient, project_id: str, **overrides: Any) -> dict[str, Any]:
    resp = await client.post(objective_url(project_id), json={**DRAFT, **overrides})
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


async def put(
    client: httpx.AsyncClient, project_id: str, base: int, **changes: Any
) -> httpx.Response:
    current = (await client.get(objective_url(project_id), params={"version": base})).json()
    body = {k: current[k] for k in DRAFT if k != "sub_questions"} | {
        "sub_questions": [{"key": s["key"], "text": s["text"]} for s in current["sub_questions"]]
    }
    return await client.put(
        objective_url(project_id), json={**body, **changes, "base_version": base}
    )


def connect(migrated_db: str) -> psycopg.Connection:
    return psycopg.connect(migrated_db, autocommit=True)


# --- creation and retrieval -------------------------------------------------------------


async def test_create_and_retrieve_full_objective(client: httpx.AsyncClient) -> None:
    project_id = await create_project(client, goal="find_gap")
    assert (await client.get(objective_url(project_id))).status_code == 404

    created = await create(client, project_id)
    assert created["version"] == 1 and created["is_active"]
    assert created["based_on_version"] is None and created["source"] == "user_edit"
    # Level and goal default to the project's.
    assert created["expertise_level"] == "beginner" and created["goal"] == "find_gap"
    assert [(s["key"], s["ordinal"]) for s in created["sub_questions"]] == [("SQ1", 1), ("SQ2", 2)]
    assert created["completeness"] == {"complete": True, "errors": [], "missing": []}

    got = (await client.get(objective_url(project_id))).json()
    assert got == created
    for field in (
        "domain",
        "subdomains",
        "target_tasks",
        "problem_areas",
        "focus_concepts",
        "keywords",
        "synonyms",
        "exclusions",
        "expected_outcomes",
        "user_context",
        "notes",
    ):
        assert got[field] == DRAFT[field], field
    assert got["constraints"]["datasets"] == {
        "required": ["QM9"],
        "preferred": [],
        "excluded": [],
        "open_access_only": True,
    }
    assert got["constraints"]["compute"]["gpu_hours"] == 100

    again = await client.post(objective_url(project_id), json=DRAFT)
    assert again.status_code == 409


async def test_incomplete_objective_can_be_saved_and_reports_gaps(
    client: httpx.AsyncClient,
) -> None:
    project_id = await create_project(client)
    resp = await client.post(objective_url(project_id), json={"core_question": "What is RL?"})
    assert resp.status_code == 201
    report = resp.json()["completeness"]
    assert not report["complete"]
    assert {m["field"] for m in report["missing"]} >= {"sub_questions", "domain"}


async def test_invalid_objectives_are_rejected(client: httpx.AsyncClient) -> None:
    project_id = await create_project(client)
    url = objective_url(project_id)
    assert (await client.post(url, json={"core_question": ""})).status_code == 422
    assert (await client.post(url, json={**DRAFT, "extra": 1})).status_code == 422
    clash = await client.post(url, json={**DRAFT, "exclusions": ["gnn"]})
    assert clash.status_code == 422
    assert clash.json()["issues"][0]["code"] == "contradiction"
    seven = [{"text": f"question number {i}"} for i in range(7)]
    assert (await client.post(url, json={**DRAFT, "sub_questions": seven})).status_code == 422
    keyed = [{"key": "SQ1", "text": "a keyed question"}]
    assert (await client.post(url, json={**DRAFT, "sub_questions": keyed})).status_code == 422
    assert (await client.get(url)).status_code == 404  # nothing was saved

    report = (await client.post(f"{url}/validate", json={**DRAFT, "exclusions": ["GNN"]})).json()
    assert not report["complete"] and report["errors"][0]["field"] == "exclusions"
    ok = (await client.post(f"{url}/validate", json=DRAFT)).json()
    assert ok["complete"]
    assert (await client.get(url)).status_code == 404  # validate never saves


# --- versions -----------------------------------------------------------------------------


async def test_update_creates_new_version_and_preserves_history(
    client: httpx.AsyncClient,
) -> None:
    project_id = await create_project(client)
    await create(client, project_id)

    resp = await put(
        client,
        project_id,
        1,
        core_question="Which GNNs work best on small datasets?",
        change_summary="narrowed",
    )
    assert resp.status_code == 201, resp.text
    v2 = resp.json()
    assert v2["version"] == 2 and v2["based_on_version"] == 1 and v2["is_active"]
    assert v2["change_summary"] == "narrowed"
    # Sub-questions are copied with the same keys, as new rows of the new version.
    assert [s["key"] for s in v2["sub_questions"]] == ["SQ1", "SQ2"]

    v1 = (await client.get(objective_url(project_id), params={"version": 1})).json()
    assert v1["core_question"] == DRAFT["core_question"] and not v1["is_active"]
    assert {s["id"] for s in v1["sub_questions"]}.isdisjoint({s["id"] for s in v2["sub_questions"]})

    versions = (await client.get(f"{objective_url(project_id)}/versions")).json()
    assert [(v["version"], v["is_active"]) for v in versions] == [(2, True), (1, False)]

    # An edit that changes nothing creates no version.
    same = await put(client, project_id, 2)
    assert same.status_code == 200 and same.json()["version"] == 2

    assert (await client.get(objective_url(project_id), params={"version": 9})).status_code == 404


async def test_activate_earlier_version_and_edit_from_it(client: httpx.AsyncClient) -> None:
    project_id = await create_project(client)
    await create(client, project_id)
    await put(client, project_id, 1, domain="chemistry")

    resp = await client.post(f"{objective_url(project_id)}/active", json={"version": 1})
    assert resp.status_code == 200 and resp.json()["version"] == 1 and resp.json()["is_active"]
    assert (await client.get(objective_url(project_id))).json()["version"] == 1

    stale = await put(client, project_id, 2, domain="biology")
    assert stale.status_code == 409
    v3 = await put(client, project_id, 1, domain="biology")
    assert v3.status_code == 201
    assert v3.json()["version"] == 3 and v3.json()["based_on_version"] == 1

    missing = await client.post(f"{objective_url(project_id)}/active", json={"version": 7})
    assert missing.status_code == 404


async def test_concurrent_updates_one_wins_one_conflicts(client: httpx.AsyncClient) -> None:
    project_id = await create_project(client)
    await create(client, project_id)
    first, second = await asyncio.gather(
        put(client, project_id, 1, domain="chemistry"),
        put(client, project_id, 1, domain="biology"),
    )
    assert sorted([first.status_code, second.status_code]) == [201, 409]
    versions = (await client.get(f"{objective_url(project_id)}/versions")).json()
    assert [v["version"] for v in versions] == [2, 1]
    loser = first if first.status_code == 409 else second
    assert loser.json()["active_version"] == 2

    # Concurrent sub-question edits on the same base: also exactly one new version.
    url = f"{objective_url(project_id)}/sub-questions"
    results = await asyncio.gather(
        *[client.post(url, json={"base_version": 2, "text": f"new question {i}"}) for i in range(3)]
    )
    assert sorted(r.status_code for r in results) == [201, 409, 409]
    assert (await client.get(objective_url(project_id))).json()["version"] == 3


async def test_concurrent_creates_produce_one_objective(client: httpx.AsyncClient) -> None:
    project_id = await create_project(client)
    results = await asyncio.gather(
        *[client.post(objective_url(project_id), json=DRAFT) for _ in range(3)]
    )
    assert sorted(r.status_code for r in results) == [201, 409, 409]


# --- sub-questions ------------------------------------------------------------------------


async def test_sub_question_add_update_remove_versions_and_stable_keys(
    client: httpx.AsyncClient,
) -> None:
    project_id = await create_project(client)
    await create(client, project_id)
    url = f"{objective_url(project_id)}/sub-questions"

    added = await client.post(url, json={"base_version": 1, "text": "Which datasets are open?"})
    assert added.status_code == 201
    assert [s["key"] for s in added.json()["sub_questions"]] == ["SQ1", "SQ2", "SQ3"]
    assert added.json()["change_summary"] == "added a sub-question"

    edited = await client.patch(f"{url}/SQ2", json={"base_version": 2, "text": "Reworded SQ2"})
    assert edited.status_code == 201
    v3 = edited.json()
    assert [s["text"] for s in v3["sub_questions"] if s["key"] == "SQ2"] == ["Reworded SQ2"]

    removed = await client.delete(f"{url}/SQ3", params={"base_version": 3})
    assert removed.status_code == 201
    assert [s["key"] for s in removed.json()["sub_questions"]] == ["SQ1", "SQ2"]

    # A removed key is never reused: the next one is SQ4.
    again = await client.post(url, json={"base_version": 4, "text": "Another new question"})
    assert [s["key"] for s in again.json()["sub_questions"]] == ["SQ1", "SQ2", "SQ4"]

    # History keeps every earlier version's sub-questions.
    v2 = (await client.get(objective_url(project_id), params={"version": 2})).json()
    assert [s["text"] for s in v2["sub_questions"]][1] == DRAFT["sub_questions"][1]["text"]
    assert len(v2["sub_questions"]) == 3

    assert (
        await client.patch(f"{url}/SQ9", json={"base_version": 5, "text": "x" * 5})
    ).status_code == 404
    assert (await client.delete(f"{url}/SQ3", params={"base_version": 5})).status_code == 404
    assert (await client.delete(f"{url}/SQ1", params={"base_version": 1})).status_code == 409
    # Unknown keys in a full update are rejected.
    bad = await put(client, project_id, 5, sub_questions=[{"key": "SQ3", "text": "resurrected"}])
    assert bad.status_code == 422
    # Seven sub-questions are too many.
    six = await put(
        client, project_id, 5, sub_questions=[{"text": f"question {i}"} for i in range(6)]
    )
    assert six.status_code == 201
    seventh = await client.post(url, json={"base_version": 6, "text": "one too many"})
    assert seventh.status_code == 422


def _graph(conn: psycopg.Connection, project_id: str) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT o.version, q.key, n.kind, n.scope_project_id FROM research_objectives o "
        "JOIN structural_relations r ON r.parent_uid = o.id AND r.type = 'PART_OF' "
        "JOIN objective_sub_questions q ON q.id = r.child_uid "
        "JOIN graph_nodes n ON n.uid = q.id WHERE o.project_id = %s ORDER BY 1, 2",
        (project_id,),
    ).fetchall()


async def test_each_sub_question_belongs_to_exactly_one_objective_version(
    client: httpx.AsyncClient, migrated_db: str
) -> None:
    project_id = await create_project(client)
    await create(client, project_id)
    await put(client, project_id, 1, domain="chemistry")
    with connect(migrated_db) as conn:
        rows = _graph(conn, project_id)
        pid = uuid.UUID(project_id)
        assert rows == [
            (1, "SQ1", "Topic", pid),
            (1, "SQ2", "Topic", pid),
            (2, "SQ1", "Topic", pid),
            (2, "SQ2", "Topic", pid),
        ]
        counts = conn.execute(
            "SELECT count(*) FROM structural_relations r JOIN research_objectives o "
            "ON o.id = r.parent_uid WHERE o.project_id = %s GROUP BY r.child_uid",
            (project_id,),
        ).fetchall()
        assert {c for (c,) in counts} == {1}


# --- database rules (direct SQL) ----------------------------------------------------------


def _objective(conn: psycopg.Connection, project_id: Any, version: int) -> uuid.UUID:
    oid = uuid7()
    conn.execute(
        "INSERT INTO research_objectives (id, project_id, version, core_question, "
        "expertise_level, goal, source) VALUES (%s, %s, %s, 'q?', 'beginner', 'find_gap', "
        "'user_edit')",
        (oid, project_id, version),
    )
    return oid


def _sub_question(conn: psycopg.Connection, key: str = "SQ1") -> uuid.UUID:
    sid = uuid7()
    conn.execute(
        "INSERT INTO objective_sub_questions (id, key, text, ordinal) VALUES (%s, %s, 'sq', 1)",
        (sid, key),
    )
    return sid


def _part_of(conn: psycopg.Connection, child: Any, parent: Any, scope: Any) -> None:
    conn.execute(
        "INSERT INTO structural_relations (id, type, child_uid, child_kind, parent_uid, "
        "parent_kind, scope_project_id) VALUES (%s, 'PART_OF', %s, 'Topic', %s, 'Objective', %s)",
        (uuid7(), child, parent, scope),
    )


async def test_cardinality_scope_and_immutability_are_enforced_by_the_database(
    client: httpx.AsyncClient, migrated_db: str
) -> None:
    p1 = uuid.UUID(await create_project(client))
    p2 = uuid.UUID(await create_project(client))
    with connect(migrated_db) as conn:
        with conn.transaction():
            o1 = _objective(conn, p1, 1)
            o2 = _objective(conn, p2, 1)
            sq = _sub_question(conn)
            _part_of(conn, sq, o1, p1)

        # A sub-question without an objective fails at commit.
        with pytest.raises(errors.CheckViolation, match="exactly one PART_OF"):
            with conn.transaction():
                _sub_question(conn, "SQ2")
        # A second objective (same project) fails at commit.
        with pytest.raises(errors.CheckViolation, match="found 2"):
            with conn.transaction():
                _part_of(conn, sq, _objective(conn, p1, 2), p1)
        # Removing the link without deleting the sub-question fails at commit.
        with pytest.raises(errors.CheckViolation, match="found 0"):
            with conn.transaction():
                conn.execute("DELETE FROM structural_relations WHERE child_uid = %s", (sq,))
        # Across projects, or with the wrong scope, fails immediately.
        with pytest.raises(errors.CheckViolation, match="different projects"):
            _part_of(conn, sq, o2, p1)
        with pytest.raises(errors.CheckViolation, match="scope"), conn.transaction():
            _part_of(conn, _sub_question(conn, "SQ3"), o1, p2)
        # Only the allowed endpoint combination.
        with pytest.raises(errors.CheckViolation, match="not an allowed combination"):
            conn.execute(
                "INSERT INTO structural_relations (id, type, child_uid, child_kind, parent_uid, "
                "parent_kind, scope_project_id) VALUES (%s, 'PART_OF', %s, 'Objective', %s, "
                "'Objective', %s)",
                (uuid7(), o1, o1, p1),
            )
        # Versions and their sub-questions never change and are not deleted on their own.
        with pytest.raises(errors.CheckViolation, match="immutable"):
            conn.execute("UPDATE research_objectives SET core_question = 'x' WHERE id = %s", (o1,))
        with pytest.raises(errors.CheckViolation, match="immutable"):
            conn.execute("UPDATE objective_sub_questions SET text = 'x' WHERE id = %s", (sq,))
        with pytest.raises(errors.CheckViolation, match="deleted only"):
            conn.execute("DELETE FROM research_objectives WHERE id = %s", (o1,))
        with pytest.raises(errors.CheckViolation, match="deleted only"):
            conn.execute("DELETE FROM objective_sub_questions WHERE id = %s", (sq,))
        with pytest.raises(errors.CheckViolation, match="immutable"):
            conn.execute("UPDATE structural_relations SET role = 'x' WHERE child_uid = %s", (sq,))
        # The active version must belong to the project.
        with pytest.raises(errors.ForeignKeyViolation):
            conn.execute("UPDATE projects SET active_objective_id = %s WHERE id = %s", (o2, p1))
        # The sub-question node carries its objective's project scope.
        scope = conn.execute("SELECT scope_project_id FROM graph_nodes WHERE uid = %s", (sq,))
        assert scope.fetchone() == (p1,)

        # Deleting the project cascades: objectives, links, sub-questions and their nodes.
        conn.execute("DELETE FROM projects WHERE id = ANY(%s)", ([p1, p2],))
        assert conn.execute(
            "SELECT count(*) FROM objective_sub_questions WHERE id = %s", (sq,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM graph_nodes WHERE uid = ANY(%s)", ([o1, o2, sq],)
        ).fetchone() == (0,)


# --- historical records keep their version ------------------------------------------------


async def test_runs_and_project_items_keep_their_original_objective_version(
    client: httpx.AsyncClient, migrated_db: str
) -> None:
    project_id = await create_project(client)
    runs_url = f"{API}/projects/{project_id}/runs"

    before = (await client.post(runs_url, json={"workflow": "dummy"})).json()
    await create(client, project_id)
    run_v1 = (await client.post(runs_url, json={"workflow": "dummy"})).json()
    added = await client.post(
        f"{API}/projects/{project_id}/papers", json={"identifier": "arXiv:1706.03762"}
    )
    assert added.status_code == 201, added.text

    await put(client, project_id, 1, domain="chemistry")
    run_v2 = (await client.post(runs_url, json={"workflow": "dummy"})).json()
    await client.post(f"{API}/projects/{project_id}/objective/active", json={"version": 1})
    run_back = (await client.post(runs_url, json={"workflow": "dummy"})).json()

    async def version_of(run: dict[str, Any]) -> Any:
        return (await client.get(f"{API}/runs/{run['id']}")).json()["objective_version"]

    assert [await version_of(r) for r in (before, run_v1, run_v2, run_back)] == [None, 1, 2, 1]
    with connect(migrated_db) as conn:
        item = conn.execute(
            "SELECT item_id, objective_version FROM project_items WHERE project_id = %s",
            (project_id,),
        ).fetchone()
        assert item is not None and item[1] == 1
        with pytest.raises(errors.CheckViolation, match="cannot be changed"):
            conn.execute(
                "UPDATE project_items SET objective_version = 2 WHERE project_id = %s",
                (project_id,),
            )
        with pytest.raises(errors.CheckViolation, match="cannot be changed"):
            conn.execute(
                "UPDATE research_runs SET objective_version = 2 WHERE id = %s", (run_v1["id"],)
            )
        # Other updates of those rows still work.
        conn.execute(
            "UPDATE project_items SET reading_status = reading_status WHERE project_id = %s",
            (project_id,),
        )
        # A version that does not exist cannot be recorded.
        with pytest.raises(errors.ForeignKeyViolation):
            conn.execute(
                "UPDATE research_runs SET objective_version = 9 WHERE id = %s", (before["id"],)
            )


# --- project isolation and authorization --------------------------------------------------


def _foreign_project(conn: psycopg.Connection) -> uuid.UUID:
    user_id, project_id = uuid7(), uuid7()
    conn.execute(
        "INSERT INTO users (id, display_name, auth_provider) VALUES (%s, 'Other', 'password')",
        (user_id,),
    )
    conn.execute(
        "INSERT INTO projects (id, user_id, title, topic, expertise_level, goal) "
        "VALUES (%s, %s, 'theirs', 'theirs', 'advanced', 'find_gap')",
        (project_id, user_id),
    )
    conn.execute(
        "INSERT INTO project_members (project_id, user_id, role) VALUES (%s, %s, 'owner')",
        (project_id, user_id),
    )
    return project_id


async def test_other_users_projects_are_invisible(
    client: httpx.AsyncClient, migrated_db: str
) -> None:
    with connect(migrated_db) as conn:
        other = str(_foreign_project(conn))
    url = objective_url(other)
    calls = [
        client.get(url),
        client.post(url, json=DRAFT),
        client.put(url, json={**DRAFT, "base_version": 1}),
        client.get(f"{url}/versions"),
        client.post(f"{url}/active", json={"version": 1}),
        client.post(f"{url}/sub-questions", json={"base_version": 1, "text": "abc"}),
        client.patch(f"{url}/sub-questions/SQ1", json={"base_version": 1, "text": "abc"}),
        client.delete(f"{url}/sub-questions/SQ1", params={"base_version": 1}),
        client.post(f"{url}/validate", json=DRAFT),
    ]
    assert {r.status_code for r in await asyncio.gather(*calls)} == {404}
    with connect(migrated_db) as conn:
        assert conn.execute(
            "SELECT count(*) FROM research_objectives WHERE project_id = %s", (other,)
        ).fetchone() == (0,)


async def test_versions_are_isolated_per_project(client: httpx.AsyncClient) -> None:
    a = await create_project(client)
    b = await create_project(client)
    await create(client, a)
    await put(client, a, 1, domain="chemistry")
    created_b = await create(client, b)
    assert created_b["version"] == 1  # numbering is per project
    assert [s["key"] for s in created_b["sub_questions"]] == ["SQ1", "SQ2"]
    assert (await client.post(f"{objective_url(b)}/active", json={"version": 2})).status_code == 404


async def test_viewers_can_read_but_not_change(client: httpx.AsyncClient, migrated_db: str) -> None:
    project_id = await create_project(client)
    await create(client, project_id)
    with connect(migrated_db) as conn:
        conn.execute(
            "UPDATE project_members SET role = 'viewer' WHERE project_id = %s", (project_id,)
        )
    url = objective_url(project_id)
    assert (await client.get(url)).status_code == 200
    assert (await client.get(f"{url}/versions")).status_code == 200
    assert (await client.post(f"{url}/validate", json=DRAFT)).status_code == 200
    writes = [
        client.post(url, json=DRAFT),
        put(client, project_id, 1, domain="x"),
        client.post(f"{url}/active", json={"version": 1}),
        client.post(f"{url}/sub-questions", json={"base_version": 1, "text": "abc"}),
        client.patch(f"{url}/sub-questions/SQ1", json={"base_version": 1, "text": "abc"}),
        client.delete(f"{url}/sub-questions/SQ1", params={"base_version": 1}),
    ]
    assert {r.status_code for r in await asyncio.gather(*writes)} == {403}
    assert len((await client.get(f"{url}/versions")).json()) == 1


async def test_interleaved_transactions_cannot_both_create_a_version(app: FastAPI) -> None:
    """Two edits from the same base in overlapping transactions: the second waits for the
    project lock, then sees the new active version and gets a conflict."""
    sessions: async_sessionmaker[AsyncSession] = app.state.sessions
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project_id = uuid.UUID(await create_project(client))
        await create(client, str(project_id))
    edit_a = ObjectiveContent.model_validate({**DRAFT, "domain": "a"})
    edit_b = ObjectiveContent.model_validate({**DRAFT, "domain": "b"})

    a_written = asyncio.Event()
    release_a = asyncio.Event()

    async def first() -> int:
        async with sessions() as s, s.begin():
            out, _ = await service.update_objective(s, project_id, None, 1, edit_a)
            a_written.set()
            await release_a.wait()
            return out.version

    async def second() -> None:
        await a_written.wait()
        async with sessions() as s, s.begin():
            await service.update_objective(s, project_id, None, 1, edit_b)

    task_a = asyncio.create_task(first())
    task_b = asyncio.create_task(second())
    await a_written.wait()
    await asyncio.sleep(0.2)
    assert not task_b.done()  # blocked on the project lock while A's transaction is open
    release_a.set()
    assert await task_a == 2
    with pytest.raises(Conflict):
        await task_b
    async with sessions() as s:
        assert [v.version for v in await service.list_versions(s, project_id)] == [2, 1]
