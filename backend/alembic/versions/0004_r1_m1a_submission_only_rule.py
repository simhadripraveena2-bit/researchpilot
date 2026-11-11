"""R1 M1a: submission_only only when the work has no public-availability claim.

Aligns the first-public invariant trigger with the Date Resolver (ARCHITECTURE §4.8.4,
DATABASE_SCHEMA §14): the arXiv v1 submission may be the first public event (basis
``submission_only``) only when no public-availability claim of any precision exists on any
of the work's manifestations - no announcement, posting, online, issue or issued event and
no reported publication date - other than claims flagged ``future_date``. Previously only a
captured announcement ruled it out.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-11
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_RULE = """        IF NEW.first_public_basis = 'submission_only' AND (
            ev.reporting_source <> 'arxiv_api' OR EXISTS (
                SELECT 1 FROM paper_dates d WHERE d.paper_id = NEW.id
                AND d.event = 'preprint_announced')) THEN
            RAISE EXCEPTION 'submission_only is only for arXiv works without a captured announcement'
                USING ERRCODE = 'check_violation';
        END IF;"""

NEW_RULE = """        IF NEW.first_public_basis = 'submission_only' AND (
            ev.reporting_source <> 'arxiv_api' OR coalesce(ev.version, 1) <> 1 OR EXISTS (
                SELECT 1 FROM paper_dates d WHERE d.paper_id = NEW.id
                AND NOT ('future_date' = ANY (d.flags))
                AND (d.event = 'reported_publication_date'
                     OR (d.event IN ('preprint_announced', 'preprint_posted', 'published_online',
                                     'issue_published', 'issued')
                         AND coalesce(d.version, 1) = 1)))) THEN
            RAISE EXCEPTION 'submission_only is only for arXiv works without any public-availability claim'
                USING ERRCODE = 'check_violation';
        END IF;"""


def _function_sql_0003() -> str:
    path = Path(__file__).with_name("0003_r1_m1a_papers_and_sources.py")
    spec = importlib.util.spec_from_file_location("rp_migration_0003", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load migration 0003")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    function_sql: str = module.FIRST_PUBLIC_SQL[0]
    if OLD_RULE not in function_sql:
        raise RuntimeError("migration 0003 trigger text changed; update 0004")
    return function_sql


def upgrade() -> None:
    sql = _function_sql_0003().replace(OLD_RULE, NEW_RULE)
    op.execute(sql.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))


def downgrade() -> None:
    op.execute(_function_sql_0003().replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
