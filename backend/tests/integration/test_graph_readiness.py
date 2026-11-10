"""R0-10 (a)-(c): node-source registration, conditions and immutable scope.

(d) GraphService and (e) the lint rule are covered in PR2 and tests/unit/test_import_rules.py.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg import errors

from researchpilot.core.ids import uuid7

pytestmark = pytest.mark.integration


def _make_user(conn: psycopg.Connection) -> uuid.UUID:
    uid = uuid7()
    conn.execute(
        "INSERT INTO users (id, display_name, auth_provider) VALUES (%s, 'User', 'password')",
        (uid,),
    )
    return uid


def _make_project(conn: psycopg.Connection, user_id: uuid.UUID) -> uuid.UUID:
    pid = uuid7()
    conn.execute(
        "INSERT INTO projects (id, user_id, title, topic, expertise_level, goal) "
        "VALUES (%s, %s, 'T', 'graph neural networks', 'beginner', 'learn_field')",
        (pid, user_id),
    )
    return pid


def test_exactly_registered_tables_have_registration_trigger(db: psycopg.Connection) -> None:
    registry = {r[0] for r in db.execute("SELECT source_table FROM node_source_registry")}
    triggered = {
        r[0]
        for r in db.execute(
            "SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE t.tgname = 'rp_register_graph_node' AND NOT t.tgisinternal"
        )
    }
    versioned = {
        r[0]
        for r in db.execute(
            "SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE t.tgname = 'rp_bump_row_version' AND NOT t.tgisinternal"
        )
    }
    assert registry == {"projects"}  # the only node source that exists in R0
    assert triggered == registry
    assert versioned == registry
    # Non-node tables never register nodes.
    assert not {"users", "research_runs", "claims", "research_items"} & triggered


def test_every_node_source_has_uuid_key_and_row_version(db: psycopg.Connection) -> None:
    rows = db.execute(
        "SELECT r.source_table, "
        "  (SELECT data_type FROM information_schema.columns "
        "   WHERE table_name = r.source_table AND column_name = 'id'), "
        "  (SELECT data_type FROM information_schema.columns "
        "   WHERE table_name = r.source_table AND column_name = 'row_version') "
        "FROM node_source_registry r"
    ).fetchall()
    for table, id_type, version_type in rows:
        assert id_type == "uuid", table
        assert version_type == "bigint", table


def test_project_registers_itself_with_its_own_scope(db: psycopg.Connection) -> None:
    pid = _make_project(db, _make_user(db))
    node = db.execute(
        "SELECT kind, scope_project_id FROM graph_nodes WHERE uid = %s", (pid,)
    ).fetchone()
    assert node == ("Project", pid)

    db.execute("UPDATE projects SET title = 'renamed' WHERE id = %s", (pid,))
    assert db.execute("SELECT row_version FROM projects WHERE id = %s", (pid,)).fetchone() == (2,)

    db.execute("DELETE FROM projects WHERE id = %s", (pid,))
    assert db.execute("SELECT count(*) FROM graph_nodes WHERE uid = %s", (pid,)).fetchone() == (0,)


def test_node_scope_and_kind_are_immutable(db: psycopg.Connection) -> None:
    user = _make_user(db)
    pid, other = _make_project(db, user), _make_project(db, user)
    db.execute("SAVEPOINT s")
    with pytest.raises(errors.CheckViolation, match="immutable"):
        db.execute("UPDATE graph_nodes SET scope_project_id = %s WHERE uid = %s", (other, pid))
    db.execute("ROLLBACK TO SAVEPOINT s")
    with pytest.raises(errors.CheckViolation, match="immutable"):
        db.execute("UPDATE graph_nodes SET kind = 'Paper' WHERE uid = %s", (pid,))
    db.execute("ROLLBACK TO SAVEPOINT s")


def test_registration_conditions_are_enforced(db: psycopg.Connection) -> None:
    """The R1 condition mechanism (e.g. reports only where type = 'proposal'), exercised on a
    temporary table through the same rp_attach_node_source() used by real migrations."""
    user = _make_user(db)
    pid = _make_project(db, user)
    db.execute(
        "CREATE TABLE tmp_reports (id uuid PRIMARY KEY, project_id uuid NOT NULL, "
        "type text NOT NULL, row_version bigint NOT NULL DEFAULT 1)"
    )
    db.execute(
        "SELECT rp_attach_node_source('tmp_reports', 'Proposal', 'own_project_id', "
        "'project_id', 'type = ''proposal''', 'test')"
    )
    proposal, discovery = uuid7(), uuid7()
    db.execute(
        "INSERT INTO tmp_reports VALUES (%s, %s, 'proposal'), (%s, %s, 'discovery')",
        (proposal, pid, discovery, pid),
    )
    nodes = dict(
        db.execute(
            "SELECT uid, scope_project_id FROM graph_nodes WHERE kind = 'Proposal'"
        ).fetchall()
    )
    assert nodes == {proposal: pid}  # the discovery report is not a node

    # Changing a row so that its registration or scope would change is refused.
    db.execute("SAVEPOINT s")
    with pytest.raises(errors.CheckViolation, match="registration"):
        db.execute("UPDATE tmp_reports SET type = 'discovery' WHERE id = %s", (proposal,))
    db.execute("ROLLBACK TO SAVEPOINT s")
    other = _make_project(db, user)
    with pytest.raises(errors.CheckViolation, match="immutable"):
        db.execute("UPDATE tmp_reports SET project_id = %s WHERE id = %s", (other, proposal))
    db.execute("ROLLBACK TO SAVEPOINT s")
