"""R0-6: migrations upgrade from empty and downgrade cleanly; models match migrations."""

from __future__ import annotations

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, pool

from researchpilot.core.ids import uuid7
from researchpilot.db import models  # noqa: F401
from researchpilot.db.base import Base
from tests.conftest import _sqlalchemy_url, alembic_config

pytestmark = pytest.mark.integration


def _user_objects(url: str) -> dict[str, set[str]]:
    with psycopg.connect(url) as conn:
        tables = {
            r[0]
            for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        }
        functions = {
            r[0]
            for r in conn.execute(
                "SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'public' AND proname LIKE 'rp\\_%'"
            )
        }
    return {"tables": tables - {"alembic_version"}, "functions": functions}


def test_upgrade_downgrade_upgrade(empty_db: str) -> None:
    cfg = alembic_config(_sqlalchemy_url(empty_db))
    command.upgrade(cfg, "head")
    after_up = _user_objects(empty_db)
    assert {"projects", "graph_nodes", "node_source_registry", "domain_events"} <= after_up[
        "tables"
    ]
    assert {"rp_register_graph_node", "rp_attach_node_source"} <= after_up["functions"]

    command.downgrade(cfg, "base")
    assert _user_objects(empty_db) == {"tables": set(), "functions": set()}

    command.upgrade(cfg, "head")
    assert _user_objects(empty_db) == after_up


def test_orm_models_match_migrated_schema(migrated_db: str) -> None:
    engine = create_engine(_sqlalchemy_url(migrated_db), poolclass=pool.NullPool)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"models and migrations differ: {diff}"


def test_required_extensions_installed(migrated_db: str) -> None:
    with psycopg.connect(migrated_db) as conn:
        names = {r[0] for r in conn.execute("SELECT extname FROM pg_extension")}
    assert {"vector", "pg_trgm"} <= names


def test_0008_objectives_upgrade_and_downgrade_with_data(empty_db: str) -> None:
    """Existing projects, runs and items survive 0008 in both directions; downgrade removes
    the objective tables, rules and nodes, and restores the 0001 registration function."""
    cfg = alembic_config(_sqlalchemy_url(empty_db))
    command.upgrade(cfg, "0007")
    user, project, run, oid, sq = (uuid7() for _ in range(5))
    with psycopg.connect(empty_db, autocommit=True) as conn:
        register_0007 = conn.execute(
            "SELECT prosrc FROM pg_proc WHERE proname = 'rp_register_graph_node'"
        ).fetchone()
        conn.execute("INSERT INTO users (id, display_name) VALUES (%s, 'u')", (user,))
        conn.execute(
            "INSERT INTO projects (id, user_id, title, topic, expertise_level, goal) "
            "VALUES (%s, %s, 't', 't', 'beginner', 'find_gap')",
            (project, user),
        )
        conn.execute(
            "INSERT INTO research_runs (id, project_id, workflow) VALUES (%s, %s, 'dummy')",
            (run, project),
        )

    command.upgrade(cfg, "0008")
    with psycopg.connect(empty_db, autocommit=True) as conn:
        # Existing rows have no objective version; nothing is back-filled or invented.
        assert conn.execute(
            "SELECT objective_version FROM research_runs WHERE id = %s", (run,)
        ).fetchone() == (None,)
        assert conn.execute(
            "SELECT active_objective_id FROM projects WHERE id = %s", (project,)
        ).fetchone() == (None,)
        with conn.transaction():
            conn.execute(
                "INSERT INTO research_objectives (id, project_id, version, core_question, "
                "expertise_level, goal, source) VALUES (%s, %s, 1, 'q?', 'beginner', "
                "'find_gap', 'user_edit')",
                (oid, project),
            )
            conn.execute(
                "INSERT INTO objective_sub_questions (id, key, text, ordinal) "
                "VALUES (%s, 'SQ1', 'sq', 1)",
                (sq,),
            )
            conn.execute(
                "INSERT INTO structural_relations (id, type, child_uid, child_kind, parent_uid, "
                "parent_kind, scope_project_id) VALUES (%s, 'PART_OF', %s, 'Topic', %s, "
                "'Objective', %s)",
                (uuid7(), sq, oid, project),
            )
            conn.execute("UPDATE research_runs SET objective_version = 1 WHERE id = %s", (run,))
        kinds = conn.execute(
            "SELECT kind FROM graph_nodes WHERE scope_project_id = %s ORDER BY kind", (project,)
        ).fetchall()
        assert kinds == [("Objective",), ("Project",), ("Topic",)]

    command.downgrade(cfg, "0007")
    with psycopg.connect(empty_db, autocommit=True) as conn:
        tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables")}
        assert tables.isdisjoint(
            {
                "research_objectives",
                "objective_sub_questions",
                "structural_relations",
                "relation_registry",
                "relation_endpoint_rules",
            }
        )
        assert conn.execute(
            "SELECT kind FROM graph_nodes WHERE scope_project_id = %s", (project,)
        ).fetchall() == [("Project",)]
        # The run survives; the version it recorded pointed at a dropped objective.
        assert conn.execute("SELECT objective_version FROM research_runs").fetchall() == [(None,)]
        assert (
            conn.execute(
                "SELECT prosrc FROM pg_proc WHERE proname = 'rp_register_graph_node'"
            ).fetchone()
            == register_0007
        )
        sources = {r[0] for r in conn.execute("SELECT source_table FROM node_source_registry")}
        assert sources == {"projects", "papers", "paper_manifestations"}
        conn.execute("UPDATE research_runs SET objective_version = 1")  # a stale R0 value

    command.upgrade(cfg, "head")  # clears values that cannot refer to an objective
    with psycopg.connect(empty_db) as conn:
        assert conn.execute("SELECT objective_version FROM research_runs").fetchall() == [(None,)]


def test_0009_relationships_upgrade_and_downgrade_with_data(empty_db: str) -> None:
    """Existing manifestations and project items get their deterministic edge ids; the raw
    author list moves to manifestation_authors; downgrade restores 0008 exactly."""
    from researchpilot.relations.ids import relation_uid

    cfg = alembic_config(_sqlalchemy_url(empty_db))
    command.upgrade(cfg, "0008")
    user, project, paper, manifestation = (uuid7() for _ in range(4))
    with psycopg.connect(empty_db, autocommit=True) as conn:
        functions_0008 = dict(
            conn.execute(
                "SELECT proname, prosrc FROM pg_proc WHERE proname IN "
                "('rp_register_graph_node', 'enforce_relation_scope', 'rp_relation_endpoints')"
            ).fetchall()
        )
        conn.execute("INSERT INTO users (id, display_name) VALUES (%s, 'u')", (user,))
        conn.execute(
            "INSERT INTO projects (id, user_id, title, topic, expertise_level, goal) "
            "VALUES (%s, %s, 't', 't', 'beginner', 'find_gap')",
            (project, user),
        )
        conn.execute("INSERT INTO research_items (id, item_type) VALUES (%s, 'paper')", (paper,))
        conn.execute(
            "INSERT INTO papers (id, title, normalized_title) VALUES (%s, 'T', 't')", (paper,)
        )
        conn.execute(
            "INSERT INTO paper_manifestations (id, paper_id, kind, server_or_venue, "
            "primary_identifier_scheme, primary_identifier_value, peer_review_label) "
            "VALUES (%s, %s, 'preprint', 'arXiv', 'arxiv', '2611.00001', "
            "'preprint_not_peer_reviewed')",
            (manifestation, paper),
        )
        conn.execute(
            "INSERT INTO paper_authors (manifestation_id, position, paper_id, raw_name) "
            "VALUES (%s, 1, %s, 'Ada Lovelace')",
            (manifestation, paper),
        )
        conn.execute(
            "INSERT INTO project_items (project_id, item_id, discovered_via) "
            "VALUES (%s, %s, 'manual')",
            (project, paper),
        )

    command.upgrade(cfg, "0009")
    with psycopg.connect(empty_db, autocommit=True) as conn:
        assert conn.execute(
            "SELECT relation_uid FROM paper_manifestations WHERE id = %s", (manifestation,)
        ).fetchone() == (relation_uid("HAS_VERSION", "paper_manifestations", paper, manifestation),)
        assert conn.execute("SELECT relation_uid, row_version FROM project_items").fetchone() == (
            relation_uid("IN_PROJECT", "project_items", paper, project),
            1,
        )
        assert conn.execute(
            "SELECT raw_name FROM manifestation_authors WHERE manifestation_id = %s",
            (manifestation,),
        ).fetchone() == ("Ada Lovelace",)
        assert conn.execute("SELECT count(*) FROM paper_authors").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM relation_registry").fetchone() == (15,)
        # A tombstone for a removed edge, to check that downgrade drops the table cleanly.
        conn.execute("DELETE FROM project_items")
        assert conn.execute("SELECT kind FROM entity_tombstones").fetchall() == [("IN_PROJECT",)]

    command.downgrade(cfg, "0008")
    with psycopg.connect(empty_db, autocommit=True) as conn:
        tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables")}
        assert {"paper_authors"} <= tables
        assert tables.isdisjoint(
            {
                "manifestation_authors",
                "citations",
                "research_relations",
                "entity_links",
                "entity_tombstones",
                "authors",
                "entities",
                "evidence_spans",
                "deletion_log",
            }
        )
        assert conn.execute(
            "SELECT raw_name, author_id FROM paper_authors WHERE manifestation_id = %s",
            (manifestation,),
        ).fetchone() == ("Ada Lovelace", None)
        assert (
            dict(
                conn.execute(
                    "SELECT proname, prosrc FROM pg_proc WHERE proname IN "
                    "('rp_register_graph_node', 'enforce_relation_scope', 'rp_relation_endpoints')"
                ).fetchall()
            )
            == functions_0008
        )
        assert conn.execute("SELECT type FROM relation_registry").fetchall() == [("PART_OF",)]
    command.upgrade(cfg, "head")
