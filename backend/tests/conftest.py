"""Shared fixtures.

Integration tests need ``TEST_DATABASE_ADMIN_URL`` (a libpq URL for a role that may create
databases, e.g. ``postgresql://postgres:postgres@127.0.0.1:5432/postgres``). Each session
creates a fresh, uniquely named database, migrates it to head, and drops it afterwards.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get("TEST_DATABASE_ADMIN_URL")


def alembic_config(sqlalchemy_url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["database_url"] = sqlalchemy_url
    return cfg


def _sqlalchemy_url(libpq_url: str) -> str:
    return libpq_url.replace("postgresql://", "postgresql+psycopg://", 1)


def _with_db(libpq_url: str, dbname: str) -> str:
    base, _, _ = libpq_url.rpartition("/")
    return f"{base}/{dbname}"


@pytest.fixture(scope="session")
def admin_url() -> str:
    if not ADMIN_URL:
        pytest.skip("TEST_DATABASE_ADMIN_URL not set (integration tests need PostgreSQL)")
    return ADMIN_URL


def create_database(admin: str) -> tuple[str, str]:
    name = f"rp_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    return name, _with_db(admin, name)


def drop_database(admin: str, name: str) -> None:
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def empty_db(admin_url: str) -> Iterator[str]:
    """A brand-new, unmigrated database (libpq URL)."""
    name, url = create_database(admin_url)
    try:
        yield url
    finally:
        drop_database(admin_url, name)


@pytest.fixture(scope="session")
def migrated_db(admin_url: str) -> Iterator[str]:
    """A database migrated to head, shared by a test session (libpq URL)."""
    name, url = create_database(admin_url)
    try:
        command.upgrade(alembic_config(_sqlalchemy_url(url)), "head")
        yield url
    finally:
        drop_database(admin_url, name)


@pytest.fixture
def db(migrated_db: str) -> Iterator[psycopg.Connection]:
    """A connection whose work is rolled back after each test."""
    with psycopg.connect(migrated_db) as conn:
        try:
            yield conn
        finally:
            conn.rollback()
