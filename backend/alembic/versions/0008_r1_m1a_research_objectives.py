"""R1 M1a: versioned research objectives, sub-questions via structural PART_OF.

Tables come from the ORM models. The hand-written SQL implements the approved rules
(ARCHITECTURE §12.4.2, §12.4.2a; DATABASE_SCHEMA §3, §16) for the part needed now:

* ``rp_register_graph_node()`` supports the ``parent_project`` scope rule: such a node is
  registered when its ``PART_OF`` link is written, with its parent's scope (immutable).
* ``relation_registry`` / ``relation_endpoint_rules`` rows for ``PART_OF`` (Topic(sub-question)
  -> Objective, exactly one per child, cascade on parent delete).
* ``rp_relation_endpoints()`` (allowed combinations + child node registration) and the generic
  registry-driven ``enforce_relation_scope()`` on ``structural_relations``.
* Deferred constraint triggers: every sub-question has exactly one ``PART_OF`` -> Objective at
  commit. Deleting an objective node cascades to its sub-questions.
* Objective versions and sub-questions are immutable (no UPDATE; DELETE only by cascade), and
  ``objective_version`` on runs and project items cannot change once set.
Revision ID: 0008
Revises: 0007
Create Date: 2026-11-12 14:13:19.223792
"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _register_function_0001() -> str:
    path = Path(__file__).with_name("0001_r0_foundation.py")
    spec = importlib.util.spec_from_file_location("rp_migration_0001", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load migration 0001")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sql = next(s for s in module.GRAPH_READINESS_SQL if "FUNCTION rp_register_graph_node" in s)
    return str(sql).replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


OLD_PARENT_RULE = """        IF v_rule = 'parent_project' THEN
            RAISE EXCEPTION 'scope rule parent_project is resolved through structural_relations (R1)';
        END IF;
"""
NEW_PARENT_RULE = """        IF v_rule = 'parent_project' THEN
            -- Registered by its PART_OF link (rp_relation_endpoints) with the parent's scope;
            -- deleting the row deletes the node (handled above), updates never move it.
            RETURN NEW;
        END IF;
"""

RULES_SQL = [
    """
    INSERT INTO relation_registry (type, class, source_table, source_column, type_discriminator,
        from_column, to_column, scope_column, scope_policy, projected, required_evidence_policy,
        introduced_in)
    VALUES ('PART_OF', 'structural', 'structural_relations', NULL, 'type', 'child_uid',
        'parent_uid', 'scope_project_id', 'project_only', true, 'none', 'R1')
    """,
    """
    INSERT INTO relation_endpoint_rules (type, from_kind, to_kind, role, child_table, cardinality,
        on_parent_delete)
    VALUES ('PART_OF', 'Topic', 'Objective', '', 'objective_sub_questions',
        'exactly_one_per_child', 'cascade_child')
    """,
    # Endpoint combinations, and registration of parent_project child nodes.
    """
    CREATE FUNCTION rp_relation_endpoints() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        rule relation_endpoint_rules%ROWTYPE;
        parent graph_nodes%ROWTYPE;
        exists_row boolean;
    BEGIN
        IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION 'structural relations are immutable (delete and re-create instead)'
                USING ERRCODE = 'check_violation';
        END IF;
        SELECT * INTO rule FROM relation_endpoint_rules
         WHERE type = NEW.type AND from_kind = NEW.child_kind AND to_kind = NEW.parent_kind
           AND role = coalesce(NEW.role, '');
        IF NOT FOUND THEN
            RAISE EXCEPTION '% from % to % (role %) is not an allowed combination',
                NEW.type, NEW.child_kind, NEW.parent_kind, coalesce(NEW.role, '-')
                USING ERRCODE = 'check_violation';
        END IF;
        SELECT * INTO parent FROM graph_nodes WHERE uid = NEW.parent_uid AND kind = NEW.parent_kind;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'parent node % (%) does not exist', NEW.parent_uid, NEW.parent_kind
                USING ERRCODE = 'foreign_key_violation';
        END IF;
        IF EXISTS (SELECT 1 FROM node_source_registry r WHERE r.source_table = rule.child_table
                   AND r.scope_rule = 'parent_project')
           AND NOT EXISTS (SELECT 1 FROM graph_nodes WHERE uid = NEW.child_uid) THEN
            EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I WHERE id = $1)', rule.child_table)
                INTO exists_row USING NEW.child_uid;
            IF NOT exists_row THEN
                RAISE EXCEPTION 'child % does not exist in %', NEW.child_uid, rule.child_table
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            INSERT INTO graph_nodes (uid, kind, scope_project_id)
            VALUES (NEW.child_uid, NEW.child_kind, parent.scope_project_id);
        END IF;
        RETURN NEW;
    END $$
    """,
    # Generic project-scope invariant, driven by relation_registry (§12.4.2a).
    """
    CREATE FUNCTION enforce_relation_scope() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        reg relation_registry%ROWTYPE;
        row_json jsonb := to_jsonb(NEW);
        a_scope uuid; b_scope uuid; r_scope uuid; a_found boolean; b_found boolean;
    BEGIN
        SELECT * INTO reg FROM relation_registry WHERE source_table = TG_TABLE_NAME
           AND (type_discriminator IS NULL OR type = row_json ->> type_discriminator);
        IF NOT FOUND THEN
            RAISE EXCEPTION 'relationship type of %.% is not registered', TG_TABLE_NAME,
                row_json ->> coalesce(reg.type_discriminator, 'type')
                USING ERRCODE = 'check_violation';
        END IF;
        SELECT scope_project_id, true INTO a_scope, a_found FROM graph_nodes
         WHERE uid = (row_json ->> reg.from_column)::uuid;
        SELECT scope_project_id, true INTO b_scope, b_found FROM graph_nodes
         WHERE uid = (row_json ->> reg.to_column)::uuid;
        IF NOT coalesce(a_found, false) OR NOT coalesce(b_found, false) THEN
            RAISE EXCEPTION '% endpoints must be registered graph nodes', reg.type
                USING ERRCODE = 'foreign_key_violation';
        END IF;
        r_scope := CASE WHEN reg.scope_column IS NULL THEN NULL
                        ELSE (row_json ->> reg.scope_column)::uuid END;
        IF a_scope IS NOT NULL AND b_scope IS NOT NULL AND a_scope <> b_scope THEN
            RAISE EXCEPTION '% may not connect nodes of different projects', reg.type
                USING ERRCODE = 'check_violation';
        END IF;
        IF coalesce(a_scope, b_scope) IS NOT NULL
           AND r_scope IS DISTINCT FROM coalesce(a_scope, b_scope) THEN
            RAISE EXCEPTION '% must carry the scope of its project-scoped endpoint', reg.type
                USING ERRCODE = 'check_violation';
        END IF;
        IF reg.scope_policy = 'project_only' AND r_scope IS NULL THEN
            RAISE EXCEPTION '% is project-only', reg.type USING ERRCODE = 'check_violation';
        END IF;
        IF reg.scope_policy = 'global_only' AND r_scope IS NOT NULL THEN
            RAISE EXCEPTION '% is global-only', reg.type USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END $$
    """,
    # Cardinality at commit: each child has exactly one link of an exactly_one rule.
    """
    CREATE FUNCTION rp_check_exactly_one_parent(p_type text, p_child uuid, p_child_kind text)
    RETURNS void LANGUAGE plpgsql AS $$
    DECLARE
        rule relation_endpoint_rules%ROWTYPE;
        exists_row boolean;
        n integer;
    BEGIN
        FOR rule IN SELECT * FROM relation_endpoint_rules WHERE type = p_type
                    AND from_kind = p_child_kind AND cardinality = 'exactly_one_per_child' LOOP
            EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I WHERE id = $1)', rule.child_table)
                INTO exists_row USING p_child;
            IF NOT exists_row THEN
                CONTINUE;  -- the child itself was deleted
            END IF;
            SELECT count(*) INTO n FROM structural_relations
             WHERE type = rule.type AND child_uid = p_child AND parent_kind = rule.to_kind;
            IF n <> 1 THEN
                RAISE EXCEPTION '% (%) must have exactly one % -> %, found %', p_child,
                    rule.child_table, rule.type, rule.to_kind, n
                    USING ERRCODE = 'check_violation';
            END IF;
        END LOOP;
    END $$
    """,
    """
    CREATE FUNCTION rp_sub_question_has_one_objective() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        PERFORM rp_check_exactly_one_parent('PART_OF', NEW.id, 'Topic');
        RETURN NULL;
    END $$
    """,
    """
    CREATE CONSTRAINT TRIGGER rp_sub_question_part_of AFTER INSERT ON objective_sub_questions
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION rp_sub_question_has_one_objective()
    """,
    """
    CREATE FUNCTION rp_structural_cardinality() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        r structural_relations%ROWTYPE := CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    BEGIN
        PERFORM rp_check_exactly_one_parent(r.type, r.child_uid, r.child_kind);
        RETURN NULL;
    END $$
    """,
    """
    CREATE CONSTRAINT TRIGGER rp_structural_cardinality AFTER INSERT OR DELETE
        ON structural_relations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION rp_structural_cardinality()
    """,
    # Composition: deleting the parent node deletes the child rows (cascade_child).
    """
    CREATE FUNCTION rp_structural_cascade() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        rule relation_endpoint_rules%ROWTYPE;
    BEGIN
        SELECT * INTO rule FROM relation_endpoint_rules WHERE type = OLD.type
           AND from_kind = OLD.child_kind AND to_kind = OLD.parent_kind
           AND role = coalesce(OLD.role, '');
        IF FOUND AND rule.on_parent_delete = 'cascade_child'
           AND NOT EXISTS (SELECT 1 FROM graph_nodes WHERE uid = OLD.parent_uid) THEN
            EXECUTE format('DELETE FROM %I WHERE id = $1', rule.child_table) USING OLD.child_uid;
        END IF;
        RETURN OLD;
    END $$
    """,
    "CREATE TRIGGER rp_relation_10_endpoints BEFORE INSERT OR UPDATE ON structural_relations "
    "FOR EACH ROW EXECUTE FUNCTION rp_relation_endpoints()",
    "CREATE TRIGGER rp_relation_20_scope BEFORE INSERT OR UPDATE ON structural_relations "
    "FOR EACH ROW EXECUTE FUNCTION enforce_relation_scope()",
    "CREATE TRIGGER rp_relation_cascade AFTER DELETE ON structural_relations "
    "FOR EACH ROW EXECUTE FUNCTION rp_structural_cascade()",
    # Immutable versions: no UPDATE; DELETE only through a cascade (project or objective).
    """
    CREATE FUNCTION rp_immutable_version() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'UPDATE' THEN
            RAISE EXCEPTION '% rows are immutable: edit by creating a new objective version',
                TG_TABLE_NAME USING ERRCODE = 'check_violation';
        END IF;
        IF pg_trigger_depth() = 1 THEN
            RAISE EXCEPTION '% rows are deleted only with their project or objective',
                TG_TABLE_NAME USING ERRCODE = 'check_violation';
        END IF;
        RETURN OLD;
    END $$
    """,
    "CREATE TRIGGER rp_immutable_version BEFORE UPDATE OR DELETE ON research_objectives "
    "FOR EACH ROW EXECUTE FUNCTION rp_immutable_version()",
    "CREATE TRIGGER rp_immutable_version BEFORE UPDATE OR DELETE ON objective_sub_questions "
    "FOR EACH ROW EXECUTE FUNCTION rp_immutable_version()",
    # The objective version recorded on a run or project item never changes once set.
    """
    CREATE FUNCTION rp_objective_version_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.objective_version IS NOT NULL
           AND NEW.objective_version IS DISTINCT FROM OLD.objective_version THEN
            RAISE EXCEPTION 'the objective version used by %.% cannot be changed', TG_TABLE_NAME,
                OLD.objective_version USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END $$
    """,
    "CREATE TRIGGER rp_objective_version_fixed BEFORE UPDATE ON research_runs "
    "FOR EACH ROW EXECUTE FUNCTION rp_objective_version_fixed()",
    "CREATE TRIGGER rp_objective_version_fixed BEFORE UPDATE ON project_items "
    "FOR EACH ROW EXECUTE FUNCTION rp_objective_version_fixed()",
]

DOWN_SQL = [
    "DROP TRIGGER IF EXISTS rp_objective_version_fixed ON project_items",
    "DROP TRIGGER IF EXISTS rp_objective_version_fixed ON research_runs",
    "DROP FUNCTION IF EXISTS rp_objective_version_fixed()",
    "DROP TRIGGER IF EXISTS rp_immutable_version ON objective_sub_questions",
    "DROP TRIGGER IF EXISTS rp_immutable_version ON research_objectives",
    "DROP FUNCTION IF EXISTS rp_immutable_version()",
    "DROP TRIGGER IF EXISTS rp_relation_cascade ON structural_relations",
    "DROP TRIGGER IF EXISTS rp_relation_20_scope ON structural_relations",
    "DROP TRIGGER IF EXISTS rp_relation_10_endpoints ON structural_relations",
    "DROP TRIGGER IF EXISTS rp_structural_cardinality ON structural_relations",
    "DROP TRIGGER IF EXISTS rp_sub_question_part_of ON objective_sub_questions",
    "DROP FUNCTION IF EXISTS rp_structural_cascade()",
    "DROP FUNCTION IF EXISTS rp_structural_cardinality()",
    "DROP FUNCTION IF EXISTS rp_sub_question_has_one_objective()",
    "DROP FUNCTION IF EXISTS rp_check_exactly_one_parent(text, uuid, text)",
    "DROP FUNCTION IF EXISTS enforce_relation_scope()",
    "DROP FUNCTION IF EXISTS rp_relation_endpoints()",
    "SELECT rp_detach_node_source('objective_sub_questions')",
    "SELECT rp_detach_node_source('research_objectives')",
    "DELETE FROM graph_nodes WHERE kind IN ('Objective', 'Topic')",
]


def upgrade() -> None:
    # research_runs.objective_version exists since R0, before any objective could exist: a
    # value there refers to nothing (only possible after a downgrade of this migration).
    op.execute(
        "UPDATE research_runs SET objective_version = NULL WHERE objective_version IS NOT NULL"
    )
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "objective_sub_questions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "key ~ '^SQ[1-9][0-9]*$'", name=op.f("ck_objective_sub_questions_key_format")
        ),
        sa.CheckConstraint(
            "ordinal >= 1", name=op.f("ck_objective_sub_questions_ordinal_positive")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_objective_sub_questions")),
    )
    op.create_table(
        "relation_registry",
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column(
            "class",
            sa.Enum(
                "research",
                "structural",
                name="relation_class",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("source_table", sa.Text(), nullable=False),
        sa.Column("source_column", sa.Text(), nullable=True),
        sa.Column("type_discriminator", sa.Text(), nullable=True),
        sa.Column("from_column", sa.Text(), nullable=False),
        sa.Column("to_column", sa.Text(), nullable=False),
        sa.Column("scope_column", sa.Text(), nullable=True),
        sa.Column(
            "scope_policy",
            sa.Enum(
                "global_only",
                "project_only",
                "project_or_global",
                name="scope_policy",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("projected", sa.Boolean(), nullable=False),
        sa.Column("required_evidence_policy", sa.Text(), nullable=False),
        sa.Column("introduced_in", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("type", name=op.f("pk_relation_registry")),
    )
    op.create_table(
        "relation_endpoint_rules",
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("from_kind", sa.Text(), nullable=False),
        sa.Column("to_kind", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), server_default="", nullable=False),
        sa.Column("child_table", sa.Text(), nullable=False),
        sa.Column("cardinality", sa.Text(), nullable=False),
        sa.Column(
            "on_parent_delete",
            sa.Enum(
                "cascade_child",
                "detach",
                name="on_parent_delete",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["type"],
            ["relation_registry.type"],
            name=op.f("fk_relation_endpoint_rules_type_relation_registry"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "type", "from_kind", "to_kind", "role", name=op.f("pk_relation_endpoint_rules")
        ),
    )
    op.create_table(
        "research_objectives",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("core_question", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column(
            "subdomains",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "target_tasks",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "problem_areas",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "focus_concepts",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "keywords",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "synonyms",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "exclusions",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "constraints",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "expected_outcomes",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("user_context", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            "source",
            sa.Enum(
                "planner",
                "user_edit",
                "feedback_suggestion",
                name="objective_source",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("based_on_version", sa.Integer(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_research_objectives_version_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_research_objectives_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_research_objectives_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_objectives")),
        sa.UniqueConstraint("project_id", "id", name=op.f("uq_research_objectives_project_id_id")),
        sa.UniqueConstraint(
            "project_id", "version", name=op.f("uq_research_objectives_project_id_version")
        ),
    )
    op.create_table(
        "structural_relations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("child_uid", sa.UUID(), nullable=False),
        sa.Column("child_kind", sa.Text(), nullable=False),
        sa.Column("parent_uid", sa.UUID(), nullable=False),
        sa.Column("parent_kind", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("assertion", sa.Text(), server_default="structural", nullable=False),
        sa.Column("scope_project_id", sa.UUID(), nullable=True),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "assertion = 'structural'", name=op.f("ck_structural_relations_assertion_structural")
        ),
        sa.CheckConstraint(
            "type IN ('PART_OF', 'RESULT_FOR')", name=op.f("ck_structural_relations_type_allowed")
        ),
        sa.ForeignKeyConstraint(
            ["child_uid", "child_kind"],
            ["graph_nodes.uid", "graph_nodes.kind"],
            name=op.f("fk_structural_relations_child_uid_graph_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_uid", "parent_kind"],
            ["graph_nodes.uid", "graph_nodes.kind"],
            name=op.f("fk_structural_relations_parent_uid_graph_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scope_project_id"],
            ["projects.id"],
            name=op.f("fk_structural_relations_scope_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_structural_relations")),
    )
    op.create_index(
        "ix_structural_relations_parent_uid", "structural_relations", ["parent_uid"], unique=False
    )
    op.create_index(
        op.f("ix_structural_relations_scope_project_id"),
        "structural_relations",
        ["scope_project_id"],
        unique=False,
    )
    op.create_index(
        "uq_structural_relations_edge",
        "structural_relations",
        ["type", "child_uid", "parent_uid", "role"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.add_column("project_items", sa.Column("objective_version", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_project_items_objective_version",
        "project_items",
        "research_objectives",
        ["project_id", "objective_version"],
        ["project_id", "version"],
    )
    op.add_column("projects", sa.Column("active_objective_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_projects_active_objective",
        "projects",
        "research_objectives",
        ["id", "active_objective_id"],
        ["project_id", "id"],
        use_alter=True,
    )
    op.create_foreign_key(
        "fk_research_runs_objective_version",
        "research_runs",
        "research_objectives",
        ["project_id", "objective_version"],
        ["project_id", "version"],
    )
    # ### end Alembic commands ###
    register = _register_function_0001()
    if OLD_PARENT_RULE not in register:
        raise RuntimeError("migration 0001 register function changed; update 0008")
    op.execute(register.replace(OLD_PARENT_RULE, NEW_PARENT_RULE))
    op.execute(
        "SELECT rp_attach_node_source('research_objectives', 'Objective', 'own_project_id', "
        "'project_id', NULL, 'R1')"
    )
    op.execute(
        "SELECT rp_attach_node_source('objective_sub_questions', 'Topic', 'parent_project', "
        "NULL, NULL, 'R1')"
    )
    for statement in RULES_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWN_SQL:
        op.execute(statement)
    # The objectives are dropped, so recorded versions would point at nothing.
    op.execute(
        "UPDATE research_runs SET objective_version = NULL WHERE objective_version IS NOT NULL"
    )
    op.execute(_register_function_0001())
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint("fk_research_runs_objective_version", "research_runs", type_="foreignkey")
    op.drop_constraint("fk_projects_active_objective", "projects", type_="foreignkey")
    op.drop_column("projects", "active_objective_id")
    op.drop_constraint("fk_project_items_objective_version", "project_items", type_="foreignkey")
    op.drop_column("project_items", "objective_version")
    op.drop_index(
        "uq_structural_relations_edge",
        table_name="structural_relations",
        postgresql_nulls_not_distinct=True,
    )
    op.drop_index(
        op.f("ix_structural_relations_scope_project_id"), table_name="structural_relations"
    )
    op.drop_index("ix_structural_relations_parent_uid", table_name="structural_relations")
    op.drop_table("structural_relations")
    op.drop_table("research_objectives")
    op.drop_table("relation_endpoint_rules")
    op.drop_table("relation_registry")
    op.drop_table("objective_sub_questions")
    # ### end Alembic commands ###
