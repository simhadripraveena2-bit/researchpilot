"""Alembic environment: synchronous psycopg connection, metadata from the ORM models."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from researchpilot.core.settings import get_settings
from researchpilot.db import models  # noqa: F401  (registers all tables)
from researchpilot.db.base import Base

target_metadata = Base.metadata


def _url() -> str:
    url = context.config.attributes.get("database_url") or get_settings().database_url
    return str(url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
