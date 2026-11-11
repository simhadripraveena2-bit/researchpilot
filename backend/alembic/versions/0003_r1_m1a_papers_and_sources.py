"""R1 M1a: source provenance, works, manifestations, identifiers and date events.

Tables are generated from the ORM models; the hand-written parts below add the
first-public-appearance invariant trigger (DATABASE_SCHEMA §14), the title trigram index and
node-source registration for ``papers`` (Paper) and ``paper_manifestations`` (PaperVersion).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-11 00:40:59.762171
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CIRCULAR_FKS = [
    (
        "fk_papers_abstract_manifestation_id_paper_manifestations",
        "abstract_manifestation_id",
        "paper_manifestations",
    ),
    (
        "fk_papers_first_public_manifestation_id_paper_manifestations",
        "first_public_manifestation_id",
        "paper_manifestations",
    ),
    ("fk_papers_first_public_event_id_paper_dates", "first_public_event_id", "paper_dates"),
]

# DATABASE_SCHEMA §14: first_public_* is set only together, only for verified/corroborated
# confidence, from a public-availability event of this work; verified needs a primary event;
# corroborated needs a second event within +-1 day with a known, different upstream source.
# The arXiv submission timestamp is allowed only as the labelled basis 'submission_only'.
FIRST_PUBLIC_SQL = [
    """
    CREATE FUNCTION rp_check_first_public() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        ev paper_dates%ROWTYPE;
        allowed text[];
    BEGIN
        IF NEW.first_public_appearance IS NULL THEN
            IF NEW.first_public_event_id IS NOT NULL OR NEW.first_public_basis IS NOT NULL
               OR NEW.first_public_manifestation_id IS NOT NULL THEN
                RAISE EXCEPTION 'first_public_* must be set together (paper %)', NEW.id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END IF;
        IF NEW.first_public_event_id IS NULL OR NEW.first_public_basis IS NULL
           OR NEW.first_public_precision IS NULL OR NEW.first_public_manifestation_id IS NULL THEN
            RAISE EXCEPTION 'first_public_* must be set together (paper %)', NEW.id
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.date_confidence NOT IN ('verified', 'corroborated') THEN
            RAISE EXCEPTION 'first public appearance needs verified or corroborated confidence'
                USING ERRCODE = 'check_violation';
        END IF;
        SELECT * INTO ev FROM paper_dates WHERE id = NEW.first_public_event_id;
        IF NOT FOUND OR ev.paper_id <> NEW.id OR ev.manifestation_id <> NEW.first_public_manifestation_id
           OR ev.value <> NEW.first_public_appearance THEN
            RAISE EXCEPTION 'first public event must be this work''s event with the same value'
                USING ERRCODE = 'check_violation';
        END IF;
        allowed := CASE NEW.first_public_basis
            WHEN 'announced' THEN ARRAY['preprint_announced']
            WHEN 'posted' THEN ARRAY['preprint_posted']
            WHEN 'published_online' THEN ARRAY['published_online']
            WHEN 'issue' THEN ARRAY['issue_published']
            WHEN 'issued' THEN ARRAY['issued']
            WHEN 'submission_only' THEN ARRAY['preprint_submitted']
        END;
        IF NOT ev.event = ANY (allowed) THEN
            RAISE EXCEPTION 'event % cannot be a first public appearance with basis %',
                ev.event, NEW.first_public_basis USING ERRCODE = 'check_violation';
        END IF;
        IF ev.precision NOT IN ('timestamp', 'day') THEN
            RAISE EXCEPTION 'first public appearance needs day or timestamp precision'
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.first_public_basis = 'submission_only' AND (
            ev.reporting_source <> 'arxiv_api' OR EXISTS (
                SELECT 1 FROM paper_dates d WHERE d.paper_id = NEW.id
                AND d.event = 'preprint_announced')) THEN
            RAISE EXCEPTION 'submission_only is only for arXiv works without a captured announcement'
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.date_confidence = 'verified' AND NOT ev.is_primary THEN
            RAISE EXCEPTION 'verified needs a primary event' USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.date_confidence = 'corroborated' AND (ev.upstream_source = 'unknown' OR NOT EXISTS (
            SELECT 1 FROM paper_dates d WHERE d.paper_id = NEW.id AND d.id <> ev.id
            AND d.upstream_source NOT IN ('unknown', ev.upstream_source)
            AND abs(extract(epoch FROM d.value - ev.value)) <= 86400)) THEN
            RAISE EXCEPTION 'corroborated needs an independent second event within one day'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE TRIGGER rp_check_first_public BEFORE INSERT OR UPDATE ON papers
        FOR EACH ROW EXECUTE FUNCTION rp_check_first_public()
    """,
]
FIRST_PUBLIC_DOWN_SQL = [
    "DROP TRIGGER IF EXISTS rp_check_first_public ON papers",
    "DROP FUNCTION IF EXISTS rp_check_first_public()",
]


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "http_cache",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "arxiv_api",
                "arxiv_announcement_feed",
                "semantic_scholar",
                "openalex",
                "crossref",
                "biorxiv_api",
                "medrxiv_api",
                name="source_name",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_http_cache")),
    )
    op.create_index(op.f("ix_http_cache_expires_at"), "http_cache", ["expires_at"], unique=False)
    op.create_table(
        "source_rate_limits",
        sa.Column(
            "source",
            sa.Enum(
                "arxiv_api",
                "arxiv_announcement_feed",
                "semantic_scholar",
                "openalex",
                "crossref",
                "biorxiv_api",
                "medrxiv_api",
                name="source_name",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "next_slot_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("source", name=op.f("pk_source_rate_limits")),
    )
    op.create_table(
        "source_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "arxiv_api",
                "arxiv_announcement_feed",
                "semantic_scholar",
                "openalex",
                "crossref",
                "biorxiv_api",
                "medrxiv_api",
                name="source_name",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("source_entity_id", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_records")),
        sa.UniqueConstraint(
            "source",
            "source_entity_id",
            "payload_sha256",
            name=op.f("uq_source_records_source_source_entity_id_payload_sha256"),
        ),
    )
    op.create_table(
        "papers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("normalized_title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column(
            "abstract_status",
            sa.Enum(
                "available",
                "unavailable",
                "restricted",
                name="abstract_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="unavailable",
            nullable=False,
        ),
        sa.Column("abstract_manifestation_id", sa.UUID(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("venue", sa.Text(), nullable=True),
        sa.Column("publication_type", sa.Text(), nullable=True),
        sa.Column("is_survey", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_open_access", sa.Boolean(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column(
            "fields_of_study",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "citation_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "field_sources",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metadata_level",
            sa.Enum(
                "stub",
                "metadata",
                "full_text",
                name="metadata_level",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="metadata",
            nullable=False,
        ),
        sa.Column("first_public_appearance", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "first_public_basis",
            sa.Enum(
                "announced",
                "posted",
                "published_online",
                "issue",
                "issued",
                "submission_only",
                name="first_public_basis",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "first_public_precision",
            sa.Enum(
                "timestamp",
                "day",
                "month",
                "year",
                name="date_precision",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("first_public_manifestation_id", sa.UUID(), nullable=True),
        sa.Column("first_public_event_id", sa.UUID(), nullable=True),
        sa.Column("candidate_public_date", sa.Date(), nullable=True),
        sa.Column(
            "date_confidence",
            sa.Enum(
                "verified",
                "corroborated",
                "source_agreement",
                "single_source",
                "conflicting",
                "uncertain",
                name="date_confidence",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="uncertain",
            nullable=False,
        ),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["id"],
            ["research_items.id"],
            name=op.f("fk_papers_id_research_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_papers")),
    )
    op.create_index(
        op.f("ix_papers_first_public_appearance"),
        "papers",
        ["first_public_appearance"],
        unique=False,
    )
    op.create_index(op.f("ix_papers_year"), "papers", ["year"], unique=False)
    op.create_table(
        "project_items",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column(
            "inclusion",
            sa.Enum(
                "candidate",
                "included",
                "excluded",
                name="inclusion",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="candidate",
            nullable=False,
        ),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismiss_reason", sa.Text(), nullable=True),
        sa.Column(
            "discovered_via",
            sa.Enum(
                "search",
                "reference",
                "citation",
                "recommendation",
                "manual",
                "probe",
                "latest_scan",
                "monitor",
                name="discovered_via",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("discovered_in_run_id", sa.UUID(), nullable=True),
        sa.Column("discovered_from_item_id", sa.UUID(), nullable=True),
        sa.Column(
            "reading_status",
            sa.Enum(
                "unread",
                "to_read",
                "reading",
                "read",
                "skipped",
                name="reading_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="unread",
            nullable=False,
        ),
        sa.Column("last_section_id", sa.UUID(), nullable=True),
        sa.Column("is_saved", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["discovered_from_item_id"],
            ["research_items.id"],
            name=op.f("fk_project_items_discovered_from_item_id_research_items"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["discovered_in_run_id"],
            ["research_runs.id"],
            name=op.f("fk_project_items_discovered_in_run_id_research_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["research_items.id"],
            name=op.f("fk_project_items_item_id_research_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_items_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("project_id", "item_id", name=op.f("pk_project_items")),
    )
    op.create_table(
        "paper_manifestations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "preprint",
                "published",
                "other",
                name="manifestation_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("server_or_venue", sa.Text(), nullable=False),
        sa.Column(
            "primary_identifier_scheme",
            sa.Enum(
                "doi",
                "arxiv",
                "s2_paper",
                "s2_corpus",
                "openalex",
                "pmid",
                "pmcid",
                "dblp",
                "acl",
                name="identifier_scheme",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("primary_identifier_value", sa.Text(), nullable=False),
        sa.Column(
            "peer_review_label",
            sa.Enum(
                "preprint_not_peer_reviewed",
                "journal_version",
                "unknown",
                name="peer_review_label",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("license", sa.Text(), nullable=True),
        sa.Column("is_open_access", sa.Boolean(), nullable=True),
        sa.Column("created_from_source_record_id", sa.UUID(), nullable=True),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_from_source_record_id"],
            ["source_records.id"],
            name=op.f("fk_paper_manifestations_created_from_source_record_id_source_records"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_paper_manifestations_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_manifestations")),
        sa.UniqueConstraint(
            "primary_identifier_scheme",
            "primary_identifier_value",
            name=op.f("uq_paper_manifestations_primary_identifier_scheme_primary_identifier_value"),
        ),
    )
    op.create_index(
        "ix_paper_manifestations_paper_id_kind",
        "paper_manifestations",
        ["paper_id", "kind"],
        unique=False,
    )
    op.create_table(
        "paper_authors",
        sa.Column("manifestation_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=True),
        sa.Column("raw_name", sa.Text(), nullable=False),
        sa.Column(
            "raw_affiliations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["manifestation_id"],
            ["paper_manifestations.id"],
            name=op.f("fk_paper_authors_manifestation_id_paper_manifestations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_paper_authors_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("manifestation_id", "position", name=op.f("pk_paper_authors")),
    )
    op.create_index(op.f("ix_paper_authors_paper_id"), "paper_authors", ["paper_id"], unique=False)
    op.create_table(
        "paper_dates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("manifestation_id", sa.UUID(), nullable=False),
        sa.Column(
            "event",
            sa.Enum(
                "preprint_submitted",
                "preprint_announced",
                "preprint_posted",
                "version_submitted",
                "version_announced",
                "version_posted",
                "accepted",
                "published_online",
                "issue_published",
                "issued",
                "reported_publication_date",
                "index_created",
                "metadata_updated",
                "metadata_deposited",
                "metadata_indexed",
                "first_seen_by_researchpilot",
                name="date_event",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("value", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "precision",
            sa.Enum(
                "timestamp",
                "day",
                "month",
                "year",
                name="date_precision",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column(
            "reporting_source",
            sa.Enum(
                "arxiv_api",
                "arxiv_announcement_feed",
                "biorxiv_api",
                "medrxiv_api",
                "crossref",
                "openalex",
                "semantic_scholar",
                "researchpilot",
                name="reporting_source",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "upstream_source",
            sa.Enum(
                "arxiv",
                "biorxiv",
                "medrxiv",
                "crossref",
                "pubmed",
                "publisher",
                "datacite",
                "unknown",
                name="upstream_source",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("upstream_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_record_id", sa.UUID(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "flags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["manifestation_id"],
            ["paper_manifestations.id"],
            name=op.f("fk_paper_dates_manifestation_id_paper_manifestations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_paper_dates_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_records.id"],
            name=op.f("fk_paper_dates_source_record_id_source_records"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_dates")),
    )
    op.create_index(
        op.f("ix_paper_dates_manifestation_id"), "paper_dates", ["manifestation_id"], unique=False
    )
    op.create_index(
        "ix_paper_dates_paper_id_event", "paper_dates", ["paper_id", "event"], unique=False
    )
    op.create_index(
        "uq_paper_dates_claim",
        "paper_dates",
        [
            "manifestation_id",
            "event",
            sa.literal_column("coalesce(version, 0)"),
            "reporting_source",
            "value",
            "precision",
        ],
        unique=True,
    )
    op.create_table(
        "paper_identifiers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("manifestation_id", sa.UUID(), nullable=False),
        sa.Column(
            "scheme",
            sa.Enum(
                "doi",
                "arxiv",
                "s2_paper",
                "s2_corpus",
                "openalex",
                "pmid",
                "pmcid",
                "dblp",
                "acl",
                name="identifier_scheme",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column(
            "source",
            sa.Enum(
                "arxiv_api",
                "arxiv_announcement_feed",
                "semantic_scholar",
                "openalex",
                "crossref",
                "biorxiv_api",
                "medrxiv_api",
                name="source_name",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("source_record_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["manifestation_id"],
            ["paper_manifestations.id"],
            name=op.f("fk_paper_identifiers_manifestation_id_paper_manifestations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_paper_identifiers_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_records.id"],
            name=op.f("fk_paper_identifiers_source_record_id_source_records"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_identifiers")),
        sa.UniqueConstraint("scheme", "value", name=op.f("uq_paper_identifiers_scheme_value")),
    )
    op.create_index(
        op.f("ix_paper_identifiers_manifestation_id"),
        "paper_identifiers",
        ["manifestation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_paper_identifiers_paper_id"), "paper_identifiers", ["paper_id"], unique=False
    )
    op.create_table(
        "paper_source_links",
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.Column("manifestation_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["manifestation_id"],
            ["paper_manifestations.id"],
            name=op.f("fk_paper_source_links_manifestation_id_paper_manifestations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_paper_source_links_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_records.id"],
            name=op.f("fk_paper_source_links_source_record_id_source_records"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("paper_id", "source_record_id", name=op.f("pk_paper_source_links")),
    )
    op.create_table(
        "paper_versions",
        sa.Column("manifestation_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source",
            sa.Enum(
                "arxiv_api",
                "arxiv_announcement_feed",
                "semantic_scholar",
                "openalex",
                "crossref",
                "biorxiv_api",
                "medrxiv_api",
                name="source_name",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("source_record_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["manifestation_id"],
            ["paper_manifestations.id"],
            name=op.f("fk_paper_versions_manifestation_id_paper_manifestations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_paper_versions_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_records.id"],
            name=op.f("fk_paper_versions_source_record_id_source_records"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("manifestation_id", "version", name=op.f("pk_paper_versions")),
    )
    op.create_index(
        op.f("ix_paper_versions_paper_id"), "paper_versions", ["paper_id"], unique=False
    )
    # ### end Alembic commands ###
    # Circular references (papers <-> manifestations/dates), added once all tables exist.
    for name, column, target in _CIRCULAR_FKS:
        op.create_foreign_key(op.f(name), "papers", target, [column], ["id"], ondelete="SET NULL")
    op.execute(
        "CREATE INDEX ix_papers_normalized_title_trgm ON papers "
        "USING gin (normalized_title gin_trgm_ops)"
    )
    for statement in FIRST_PUBLIC_SQL:
        op.execute(statement)
    # Node sources (DATABASE_SCHEMA §16.3): works and their versions are global nodes.
    op.execute("SELECT rp_attach_node_source('papers', 'Paper', 'global', NULL, NULL, 'R1')")
    op.execute(
        "SELECT rp_attach_node_source('paper_manifestations', 'PaperVersion', 'global', NULL, "
        "NULL, 'R1')"
    )


def downgrade() -> None:
    op.execute("SELECT rp_detach_node_source('paper_manifestations')")
    op.execute("SELECT rp_detach_node_source('papers')")
    op.execute("DELETE FROM graph_nodes WHERE kind IN ('Paper', 'PaperVersion')")
    for statement in FIRST_PUBLIC_DOWN_SQL:
        op.execute(statement)
    op.execute("DROP INDEX IF EXISTS ix_papers_normalized_title_trgm")
    for name, _, _ in _CIRCULAR_FKS:
        op.drop_constraint(op.f(name), "papers", type_="foreignkey")
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_paper_versions_paper_id"), table_name="paper_versions")
    op.drop_table("paper_versions")
    op.drop_table("paper_source_links")
    op.drop_index(op.f("ix_paper_identifiers_paper_id"), table_name="paper_identifiers")
    op.drop_index(op.f("ix_paper_identifiers_manifestation_id"), table_name="paper_identifiers")
    op.drop_table("paper_identifiers")
    op.drop_index("uq_paper_dates_claim", table_name="paper_dates")
    op.drop_index("ix_paper_dates_paper_id_event", table_name="paper_dates")
    op.drop_index(op.f("ix_paper_dates_manifestation_id"), table_name="paper_dates")
    op.drop_table("paper_dates")
    op.drop_index(op.f("ix_paper_authors_paper_id"), table_name="paper_authors")
    op.drop_table("paper_authors")
    op.drop_index("ix_paper_manifestations_paper_id_kind", table_name="paper_manifestations")
    op.drop_table("paper_manifestations")
    op.drop_table("project_items")
    op.drop_index(op.f("ix_papers_year"), table_name="papers")
    op.drop_index(op.f("ix_papers_first_public_appearance"), table_name="papers")
    op.drop_table("papers")
    op.drop_table("source_records")
    op.drop_table("source_rate_limits")
    op.drop_index(op.f("ix_http_cache_expires_at"), table_name="http_cache")
    op.drop_table("http_cache")
    # ### end Alembic commands ###
