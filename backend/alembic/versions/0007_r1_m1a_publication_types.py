"""R1 M1a: explicit publication type per manifestation (ARCHITECTURE §4.8.4).

Backfill from what is already stored: preprint manifestations are ``preprint``; published
ones map from the Crossref ``type`` kept on the work; Crossref records whose ``update-to``
names a correction, retraction or expression of concern are notices.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES = (
    "preprint",
    "journal_article",
    "conference_paper",
    "book_chapter",
    "book",
    "dissertation",
    "report",
    "dataset",
    "correction",
    "retraction",
    "expression_of_concern",
    "other",
)

BACKFILL = [
    "UPDATE paper_manifestations SET publication_type = 'preprint' WHERE kind = 'preprint'",
    """
    UPDATE paper_manifestations m SET publication_type = CASE p.publication_type
        WHEN 'journal-article' THEN 'journal_article'
        WHEN 'proceedings-article' THEN 'conference_paper'
        WHEN 'book-chapter' THEN 'book_chapter'
        WHEN 'book' THEN 'book'
        WHEN 'monograph' THEN 'book'
        WHEN 'dissertation' THEN 'dissertation'
        WHEN 'report' THEN 'report'
        WHEN 'dataset' THEN 'dataset'
        ELSE 'other' END
    FROM papers p WHERE p.id = m.paper_id AND m.kind <> 'preprint'
    """,
    """
    UPDATE paper_manifestations m SET publication_type = CASE
        r.payload -> 'update-to' -> 0 ->> 'type'
        WHEN 'correction' THEN 'correction' WHEN 'erratum' THEN 'correction'
        WHEN 'corrigendum' THEN 'correction' WHEN 'retraction' THEN 'retraction'
        WHEN 'withdrawal' THEN 'retraction' WHEN 'removal' THEN 'retraction'
        WHEN 'expression_of_concern' THEN 'expression_of_concern'
        ELSE m.publication_type END
    FROM source_records r WHERE r.id = m.created_from_source_record_id
    AND r.source = 'crossref' AND jsonb_typeof(r.payload -> 'update-to') = 'array'
    """,
]


def upgrade() -> None:
    op.add_column(
        "paper_manifestations",
        sa.Column(
            "publication_type",
            sa.Enum(*TYPES, name="publication_type", native_enum=False, create_constraint=True),
            server_default="other",
            nullable=False,
        ),
    )
    for statement in BACKFILL:
        op.execute(statement)


def downgrade() -> None:
    op.drop_column("paper_manifestations", "publication_type")
