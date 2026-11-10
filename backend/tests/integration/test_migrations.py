"""R0-6: migrations upgrade from empty and downgrade cleanly; models match migrations."""

from __future__ import annotations

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, pool

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
