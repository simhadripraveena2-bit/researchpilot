"""R0 foundation: identity, projects, runs, outbox, claims and graph readiness.

Tables are generated from the ORM models; the hand-written SQL below adds the graph-readiness
mechanisms (ARCHITECTURE §12.2-§12.4, DATABASE_SCHEMA §16):

* ``rp_bump_row_version()``      - increments ``row_version`` on every update (sync guard).
* ``rp_register_graph_node()``   - registers/deregisters node-source rows in ``graph_nodes``
  according to their ``node_source_registry`` row (label, scope rule, condition).
* ``rp_graph_nodes_immutable()`` - a node's uid, kind and scope never change.
* ``rp_attach_node_source()``    - the only way to make a table a node source: inserts the
  registry row and attaches the triggers, so registry and triggers cannot drift apart.

Revision ID: 0001
Revises:
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRAPH_READINESS_SQL = [
    """
    CREATE FUNCTION rp_bump_row_version() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        NEW.row_version := OLD.row_version + 1;
        RETURN NEW;
    END $$
    """,
    """
    CREATE FUNCTION rp_graph_nodes_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.uid IS DISTINCT FROM OLD.uid
           OR NEW.kind IS DISTINCT FROM OLD.kind
           OR NEW.scope_project_id IS DISTINCT FROM OLD.scope_project_id THEN
            RAISE EXCEPTION 'graph node % is immutable (uid, kind and scope cannot change)', OLD.uid
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE TRIGGER graph_nodes_immutable BEFORE UPDATE ON graph_nodes
        FOR EACH ROW EXECUTE FUNCTION rp_graph_nodes_immutable()
    """,
    # Trigger arguments: label, scope_rule, scope_column ('' = none), condition ('' = always).
    """
    CREATE FUNCTION rp_register_graph_node() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        v_label     text := TG_ARGV[0];
        v_rule      text := TG_ARGV[1];
        v_scope_col text := NULLIF(TG_ARGV[2], '');
        v_condition text := NULLIF(TG_ARGV[3], '');
        v_qualifies boolean := true;
        v_scope     uuid;
        v_existing  graph_nodes%ROWTYPE;
    BEGIN
        IF TG_OP = 'DELETE' THEN
            DELETE FROM graph_nodes WHERE uid = OLD.id;
            RETURN OLD;
        END IF;

        IF v_condition IS NOT NULL THEN
            EXECUTE format('SELECT (%s) FROM (SELECT ($1).*) AS r', v_condition)
                INTO v_qualifies USING NEW;
            v_qualifies := coalesce(v_qualifies, false);
        END IF;

        v_scope := CASE v_rule
            WHEN 'global' THEN NULL
            WHEN 'self' THEN NEW.id
            WHEN 'own_project_id' THEN (to_jsonb(NEW) ->> v_scope_col)::uuid
            ELSE NULL
        END;
        IF v_rule = 'parent_project' THEN
            RAISE EXCEPTION 'scope rule parent_project is resolved through structural_relations (R1)';
        END IF;

        IF TG_OP = 'INSERT' THEN
            IF v_qualifies THEN
                INSERT INTO graph_nodes (uid, kind, scope_project_id)
                VALUES (NEW.id, v_label, v_scope);
            END IF;
            RETURN NEW;
        END IF;

        -- UPDATE: registration and scope are fixed at insert time.
        SELECT * INTO v_existing FROM graph_nodes WHERE uid = NEW.id;
        IF v_qualifies <> FOUND THEN
            RAISE EXCEPTION 'update would change graph-node registration of %.%', TG_TABLE_NAME, NEW.id
                USING ERRCODE = 'check_violation';
        END IF;
        IF FOUND AND v_existing.scope_project_id IS DISTINCT FROM v_scope THEN
            RAISE EXCEPTION 'graph node scope is immutable (%.%)', TG_TABLE_NAME, NEW.id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE FUNCTION rp_attach_node_source(
        p_table text, p_label text, p_rule text, p_scope_col text, p_condition text,
        p_introduced_in text
    ) RETURNS void LANGUAGE plpgsql AS $$
    BEGIN
        INSERT INTO node_source_registry
            (source_table, label, scope_rule, scope_column, registration_condition, introduced_in)
        VALUES (p_table, p_label, p_rule, p_scope_col, p_condition, p_introduced_in);
        EXECUTE format(
            'CREATE TRIGGER rp_register_graph_node AFTER INSERT OR UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION rp_register_graph_node(%L, %L, %L, %L)',
            p_table, p_label, p_rule, coalesce(p_scope_col, ''), coalesce(p_condition, ''));
        EXECUTE format(
            'CREATE TRIGGER rp_bump_row_version BEFORE UPDATE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION rp_bump_row_version()', p_table);
    END $$
    """,
    """
    CREATE FUNCTION rp_detach_node_source(p_table text) RETURNS void LANGUAGE plpgsql AS $$
    BEGIN
        EXECUTE format('DROP TRIGGER IF EXISTS rp_register_graph_node ON %I', p_table);
        EXECUTE format('DROP TRIGGER IF EXISTS rp_bump_row_version ON %I', p_table);
        DELETE FROM node_source_registry WHERE source_table = p_table;
    END $$
    """,
]

GRAPH_READINESS_DOWN_SQL = [
    "SELECT rp_detach_node_source('projects')",
    "DROP TRIGGER IF EXISTS graph_nodes_immutable ON graph_nodes",
    "DROP FUNCTION IF EXISTS rp_detach_node_source(text)",
    "DROP FUNCTION IF EXISTS rp_attach_node_source(text, text, text, text, text, text)",
    "DROP FUNCTION IF EXISTS rp_register_graph_node()",
    "DROP FUNCTION IF EXISTS rp_graph_nodes_immutable()",
    "DROP FUNCTION IF EXISTS rp_bump_row_version()",
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "domain_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_domain_events")),
    )
    op.create_index(
        "ix_domain_events_unprocessed",
        "domain_events",
        ["id"],
        unique=False,
        postgresql_where=sa.text("processed_at IS NULL"),
    )
    op.create_table(
        "node_source_registry",
        sa.Column("source_table", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("registration_condition", sa.Text(), nullable=True),
        sa.Column(
            "scope_rule",
            sa.Enum(
                "global",
                "self",
                "own_project_id",
                "parent_project",
                name="scope_rule",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("scope_column", sa.Text(), nullable=True),
        sa.Column("introduced_in", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("source_table", name=op.f("pk_node_source_registry")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column(
            "auth_provider",
            sa.Enum(
                "local_none",
                "oidc",
                "password",
                name="auth_provider",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="local_none",
            nullable=False,
        ),
        sa.Column("auth_subject", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("mfa_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "default_level",
            sa.Enum(
                "beginner",
                "intermediate",
                "advanced",
                name="expertise_level",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="beginner",
            nullable=False,
        ),
        sa.Column("timezone", sa.Text(), server_default="UTC", nullable=False),
        sa.Column(
            "timezone_source",
            sa.Enum(
                "browser", "user", name="timezone_source", native_enum=False, create_constraint=True
            ),
            server_default="browser",
            nullable=False,
        ),
        sa.Column(
            "preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "domain_event_deliveries",
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("consumer", sa.Text(), nullable=False),
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["domain_events.id"],
            name=op.f("fk_domain_event_deliveries_event_id_domain_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", "consumer", name=op.f("pk_domain_event_deliveries")),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column(
            "expertise_level",
            sa.Enum(
                "beginner",
                "intermediate",
                "advanced",
                name="expertise_level",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "goal",
            sa.Enum(
                "learn_field",
                "review_literature",
                "find_gap",
                "plan_experiment",
                "write_proposal",
                "track_field",
                name="project_goal",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "tutor_retention_policy",
            sa.Enum(
                "keep_until_deleted",
                "delete_after_days",
                "do_not_store",
                name="tutor_retention_policy",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="keep_until_deleted",
            nullable=False,
        ),
        sa.Column("tutor_retention_days", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "archived",
                name="project_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="active",
            nullable=False,
        ),
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
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "(tutor_retention_policy = 'delete_after_days') = (tutor_retention_days IS NOT NULL)",
            name=op.f("ck_projects_retention_days_iff_policy"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_projects_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_table(
        "claims",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "reported_finding",
                "extracted_observation",
                "ai_interpretation",
                "unverified_hypothesis",
                name="claim_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "grounding",
            sa.Enum(
                "grounded",
                "background",
                name="grounding",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "origin_type",
            sa.Enum(
                "card",
                "explanation",
                "comparison",
                "gap",
                "idea",
                "report",
                "tutor",
                name="claim_origin",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("origin_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "hidden_pending_review",
                "superseded",
                "rejected",
                name="claim_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'ai_interpretation') = (grounding IS NOT NULL)",
            name=op.f("ck_claims_grounding_iff_ai"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_claims_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claims")),
    )
    op.create_index(op.f("ix_claims_project_id"), "claims", ["project_id"], unique=False)
    op.create_table(
        "graph_nodes",
        sa.Column("uid", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("scope_project_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scope_project_id"],
            ["projects.id"],
            name=op.f("fk_graph_nodes_scope_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk_graph_nodes")),
        sa.UniqueConstraint("uid", "kind", name="uq_graph_nodes_uid_kind"),
    )
    op.create_index(
        op.f("ix_graph_nodes_scope_project_id"), "graph_nodes", ["scope_project_id"], unique=False
    )
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "owner",
                "editor",
                "viewer",
                name="project_role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_members_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_project_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("project_id", "user_id", name=op.f("pk_project_members")),
    )
    op.create_table(
        "research_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "item_type",
            sa.Enum(
                "paper",
                "method",
                "architecture",
                "algorithm",
                "dataset",
                "benchmark",
                "metric",
                "model",
                "task",
                "concept",
                "term",
                "repository",
                "gap",
                "idea",
                name="item_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_research_items_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_items")),
    )
    op.create_table(
        "research_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column(
            "workflow",
            sa.Enum(
                "dummy",
                "discovery",
                "assessment",
                "learning_setup",
                "latest_scan",
                "analysis",
                "investigation",
                "experiment_design",
                "report",
                "monitor",
                name="workflow",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "awaiting_approval",
                "succeeded",
                "partially_succeeded",
                "failed",
                "cancelled",
                name="run_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("objective_version", sa.Integer(), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_research_runs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_runs")),
    )
    op.create_index(
        op.f("ix_research_runs_project_id"), "research_runs", ["project_id"], unique=False
    )
    op.create_table(
        "checkpoints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "modified",
                "rejected",
                name="checkpoint_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("decision", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["research_runs.id"],
            name=op.f("fk_checkpoints_run_id_research_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checkpoints")),
    )
    op.create_index(op.f("ix_checkpoints_run_id"), "checkpoints", ["run_id"], unique=False)
    op.create_table(
        "claim_evidence",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("claim_id", sa.UUID(), nullable=False),
        sa.Column("evidence_span_id", sa.UUID(), nullable=True),
        sa.Column("item_id", sa.UUID(), nullable=True),
        sa.Column("signal_id", sa.UUID(), nullable=True),
        sa.Column(
            "relation",
            sa.Enum(
                "supports",
                "contradicts",
                "context",
                name="evidence_relation",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.CheckConstraint(
            "num_nonnulls(evidence_span_id, item_id, signal_id) >= 1",
            name=op.f("ck_claim_evidence_has_reference"),
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.id"],
            name=op.f("fk_claim_evidence_claim_id_claims"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["research_items.id"],
            name=op.f("fk_claim_evidence_item_id_research_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_evidence")),
    )
    op.create_index(
        op.f("ix_claim_evidence_claim_id"), "claim_evidence", ["claim_id"], unique=False
    )
    op.create_table(
        "claim_verifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("claim_id", sa.UUID(), nullable=False),
        sa.Column(
            "level",
            sa.Enum(
                "quote_verified",
                "data_derived",
                "metadata_confirmed",
                "cross_checked",
                "unverified",
                name="verification_level",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "result",
            sa.Enum(
                "pass",
                "fail",
                name="verification_result",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.id"],
            name=op.f("fk_claim_verifications_claim_id_claims"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_verifications")),
    )
    op.create_index(
        op.f("ix_claim_verifications_claim_id"), "claim_verifications", ["claim_id"], unique=False
    )
    op.create_table(
        "run_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("level", sa.Text(), server_default="info", nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["research_runs.id"],
            name=op.f("fk_run_events_run_id_research_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_events")),
    )
    op.create_index(op.f("ix_run_events_run_id"), "run_events", ["run_id"], unique=False)
    op.create_table(
        "task_executions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "succeeded",
                "failed",
                name="task_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("input_hash", sa.Text(), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["research_runs.id"],
            name=op.f("fk_task_executions_run_id_research_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_executions")),
    )
    op.create_index(op.f("ix_task_executions_run_id"), "task_executions", ["run_id"], unique=False)
    # ### end Alembic commands ###
    for statement in GRAPH_READINESS_SQL:
        op.execute(statement)
    op.execute("SELECT rp_attach_node_source('projects', 'Project', 'self', NULL, NULL, 'R0')")


def downgrade() -> None:
    for statement in GRAPH_READINESS_DOWN_SQL:
        op.execute(statement)
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_task_executions_run_id"), table_name="task_executions")
    op.drop_table("task_executions")
    op.drop_index(op.f("ix_run_events_run_id"), table_name="run_events")
    op.drop_table("run_events")
    op.drop_index(op.f("ix_claim_verifications_claim_id"), table_name="claim_verifications")
    op.drop_table("claim_verifications")
    op.drop_index(op.f("ix_claim_evidence_claim_id"), table_name="claim_evidence")
    op.drop_table("claim_evidence")
    op.drop_index(op.f("ix_checkpoints_run_id"), table_name="checkpoints")
    op.drop_table("checkpoints")
    op.drop_index(op.f("ix_research_runs_project_id"), table_name="research_runs")
    op.drop_table("research_runs")
    op.drop_table("research_items")
    op.drop_table("project_members")
    op.drop_index(op.f("ix_graph_nodes_scope_project_id"), table_name="graph_nodes")
    op.drop_table("graph_nodes")
    op.drop_index(op.f("ix_claims_project_id"), table_name="claims")
    op.drop_table("claims")
    op.drop_table("projects")
    op.drop_table("domain_event_deliveries")
    op.drop_table("users")
    op.drop_table("node_source_registry")
    op.drop_index(
        "ix_domain_events_unprocessed",
        table_name="domain_events",
        postgresql_where=sa.text("processed_at IS NULL"),
    )
    op.drop_table("domain_events")
    # ### end Alembic commands ###
    # Extensions are left installed: other databases objects may depend on them.
