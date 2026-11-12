"""Hand-written SQL for migration 0009 (relationship sources, ARCHITECTURE §12.4-12.6a).

Kept outside ``alembic/versions`` so Alembic does not treat it as a revision. Migrations load
it by path, so later changes to application code cannot alter what 0009 does.
"""

from __future__ import annotations

# UUIDv5 namespace for edge identities of composite-key link tables; equal to
# ``uuid.uuid5(uuid.NAMESPACE_URL, "https://researchpilot.dev/ns/relations")`` (relations.ids).
RELATION_NAMESPACE = "09133bc7-a119-5f7b-931f-8193f70efc07"

ESTABLISHED = "'source_metadata', 'author_reported', 'extracted', 'computed', 'inferred'"

# ----------------------------------------------------------------------------------------
# Node registration: label expressions (entities: the label follows the type).
# ----------------------------------------------------------------------------------------

REGISTER_NODE = r"""
CREATE OR REPLACE FUNCTION rp_register_graph_node() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_label     text := TG_ARGV[0];
    v_rule      text := TG_ARGV[1];
    v_scope_col text := NULLIF(TG_ARGV[2], '');
    v_condition text := NULLIF(TG_ARGV[3], '');
    v_qualifies boolean := true;
    v_scope     uuid;
    v_kind      text;
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
    -- A label starting with '=' is an expression over the row (e.g. entities by type).
    IF left(v_label, 1) = '=' THEN
        EXECUTE format('SELECT (%s) FROM (SELECT ($1).*) AS r', substr(v_label, 2))
            INTO v_kind USING NEW;
        IF v_qualifies AND v_kind IS NULL THEN
            RAISE EXCEPTION 'no graph label for %.%', TG_TABLE_NAME, NEW.id
                USING ERRCODE = 'check_violation';
        END IF;
    ELSE
        v_kind := v_label;
    END IF;

    v_scope := CASE v_rule
        WHEN 'global' THEN NULL
        WHEN 'self' THEN NEW.id
        WHEN 'own_project_id' THEN (to_jsonb(NEW) ->> v_scope_col)::uuid
        ELSE NULL
    END;
    IF v_rule = 'parent_project' THEN
        -- Registered by its PART_OF link (rp_relation_check) with the parent's scope;
        -- deleting the row deletes the node (handled above), updates never move it.
        RETURN NEW;
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF v_qualifies THEN
            INSERT INTO graph_nodes (uid, kind, scope_project_id)
            VALUES (NEW.id, v_kind, v_scope);
        END IF;
        RETURN NEW;
    END IF;

    -- UPDATE: registration, kind and scope are fixed at insert time.
    SELECT * INTO v_existing FROM graph_nodes WHERE uid = NEW.id;
    IF v_qualifies <> FOUND THEN
        RAISE EXCEPTION 'update would change graph-node registration of %.%', TG_TABLE_NAME, NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF FOUND AND (v_existing.scope_project_id IS DISTINCT FROM v_scope
                  OR v_existing.kind IS DISTINCT FROM v_kind) THEN
        RAISE EXCEPTION 'graph node kind and scope are immutable (%.%)', TG_TABLE_NAME, NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$
"""

ENTITY_LABEL = """
CREATE FUNCTION rp_entity_label(p_type text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_type IN ('method', 'algorithm', 'architecture') THEN 'Method'
        WHEN p_type = 'dataset' THEN 'Dataset'
        WHEN p_type = 'benchmark' THEN 'Benchmark'
        WHEN p_type = 'metric' THEN 'Metric'
        WHEN p_type = 'model' THEN 'Model'
        WHEN p_type IN ('task', 'concept') THEN 'Topic'
    END
$$
"""

NODE_SOURCES = [
    "SELECT rp_attach_node_source('authors', 'Author', 'global', NULL, NULL, 'R1')",
    "SELECT rp_attach_node_source('research_groups', 'ResearchGroup', 'global', NULL, NULL, 'R1')",
    # Glossary terms are learning data, not nodes (ARCHITECTURE §12.3).
    "SELECT rp_attach_node_source('entities', '=rp_entity_label(type)', 'global', NULL, "
    "'type <> ''term''', 'R1')",
]

# ----------------------------------------------------------------------------------------
# Registry: one row per type -> its single source (ARCHITECTURE §12.4.1).
# ----------------------------------------------------------------------------------------

_R = "research"
_S = "structural"
# type, class, source_table, source_column, discriminator, from, to, scope col, policy,
# projected, evidence policy
REGISTRY_ROWS: list[tuple[str, ...]] = [
    (
        "CITES",
        _R,
        "citations",
        "",
        "",
        "citing_id",
        "cited_id",
        "scope_project_id",
        "global_only",
        "t",
        "by_assertion",
    ),
    (
        "AUTHORED_BY",
        _R,
        "paper_authors",
        "",
        "",
        "paper_id",
        "author_id",
        "scope_project_id",
        "global_only",
        "t",
        "by_assertion",
    ),
    (
        "AFFILIATED_WITH",
        _R,
        "author_affiliations",
        "",
        "",
        "author_id",
        "group_id",
        "scope_project_id",
        "global_only",
        "t",
        "by_assertion",
    ),
    (
        "INTRODUCES",
        _R,
        "entity_links",
        "",
        "role",
        "subject_uid",
        "entity_id",
        "scope_project_id",
        "project_or_global",
        "t",
        "by_assertion",
    ),
    (
        "USES_METHOD",
        _R,
        "entity_links",
        "",
        "role",
        "subject_uid",
        "entity_id",
        "scope_project_id",
        "project_or_global",
        "t",
        "by_assertion",
    ),
    (
        "EVALUATES_ON",
        _R,
        "entity_links",
        "",
        "role",
        "subject_uid",
        "entity_id",
        "scope_project_id",
        "project_or_global",
        "t",
        "by_assertion",
    ),
    *[
        (
            t,
            _R,
            "research_relations",
            "",
            "type",
            "from_uid",
            "to_uid",
            "scope_project_id",
            "project_only" if t == "VALIDATED_BY" else "project_or_global",
            "t",
            "by_assertion",
        )
        for t in (
            "EXTENDS",
            "CONTRADICTS",
            "RELATED_TO",
            "ADDRESSES",
            "DERIVED_FROM",
            "VALIDATED_BY",
        )
    ],
    (
        "HAS_VERSION",
        _S,
        "paper_manifestations",
        "paper_id",
        "",
        "paper_id",
        "id",
        "",
        "global_only",
        "t",
        "none",
    ),
    (
        "IN_PROJECT",
        _S,
        "project_items",
        "",
        "",
        "item_id",
        "project_id",
        "project_id",
        "project_only",
        "t",
        "none",
    ),
]

# type, from_kind, to_kind ('*' = any kind); role '' (RESULT_FOR roles arrive in R2).
ENDPOINT_RULES: list[tuple[str, str, str]] = [
    ("CITES", "Paper", "Paper"),
    ("AUTHORED_BY", "Paper", "Author"),
    ("AFFILIATED_WITH", "Author", "ResearchGroup"),
    *[("INTRODUCES", "Paper", k) for k in ("Method", "Dataset", "Benchmark", "Metric")],
    *[("USES_METHOD", k, "Method") for k in ("Paper", "Proposal", "Experiment")],
    *[
        ("EVALUATES_ON", a, b)
        for a in ("Paper", "Method", "Proposal", "Experiment")
        for b in ("Dataset", "Benchmark")
    ],
    ("EXTENDS", "Paper", "Paper"),
    ("EXTENDS", "Method", "Method"),
    ("CONTRADICTS", "Paper", "Paper"),
    ("CONTRADICTS", "Result", "Result"),
    ("CONTRADICTS", "Paper", "Hypothesis"),
    ("RELATED_TO", "*", "*"),
    ("ADDRESSES", "Paper", "Gap"),
    ("ADDRESSES", "Paper", "Topic"),
    ("ADDRESSES", "Proposal", "Hypothesis"),
    ("ADDRESSES", "Experiment", "Hypothesis"),
    ("DERIVED_FROM", "Gap", "Limitation"),
    ("DERIVED_FROM", "Gap", "LimitationCluster"),
    ("DERIVED_FROM", "Gap", "Paper"),
    ("DERIVED_FROM", "Hypothesis", "Gap"),
    ("DERIVED_FROM", "Proposal", "Hypothesis"),
    ("VALIDATED_BY", "Hypothesis", "Result"),
    ("VALIDATED_BY", "Hypothesis", "Experiment"),
    ("HAS_VERSION", "Paper", "PaperVersion"),
    ("IN_PROJECT", "Paper", "Project"),
]


def _lit(value: str) -> str:
    return "NULL" if value == "" else "'" + value.replace("'", "''") + "'"


def registry_inserts() -> list[str]:
    rows = ",\n".join(
        "("
        + ", ".join(
            [_lit(v) for v in r[:9]] + [("true" if r[9] == "t" else "false"), _lit(r[10]), "'R1'"]
        )
        + ")"
        for r in REGISTRY_ROWS
    )
    rules = ",\n".join(
        f"('{t}', '{a}', '{b}', '', NULL, 'many', 'detach')" for t, a, b in ENDPOINT_RULES
    )
    return [
        "INSERT INTO relation_registry (type, class, source_table, source_column, "
        "type_discriminator, from_column, to_column, scope_column, scope_policy, projected, "
        "required_evidence_policy, introduced_in) VALUES\n" + rows,
        "INSERT INTO relation_endpoint_rules (type, from_kind, to_kind, role, child_table, "
        "cardinality, on_parent_delete) VALUES\n" + rules,
    ]


# ----------------------------------------------------------------------------------------
# Generic relationship triggers (driven by relation_registry).
# ----------------------------------------------------------------------------------------

FUNCTIONS = [
    f"""
    CREATE FUNCTION rp_relation_uid(p_type text, p_table text, p_from uuid, p_to uuid,
                                    p_qualifier text) RETURNS uuid
    LANGUAGE sql IMMUTABLE AS $$
        SELECT uuid_generate_v5('{RELATION_NAMESPACE}'::uuid,
            p_type || '|' || p_table || '|' || p_from::text || '|' || p_to::text || '|'
            || coalesce(p_qualifier, ''))
    $$
    """,
    # The registry row describing this row of this table. A discriminator value without a
    # registered type (entity_links roles compares_against / reports_metric) is assessment
    # data: it gets the table's columns, policy project_or_global, and is never projected.
    """
    CREATE FUNCTION rp_relation_spec(p_table text, p_row jsonb) RETURNS relation_registry
    LANGUAGE plpgsql STABLE AS $$
    DECLARE
        reg relation_registry%ROWTYPE;
        v_value text;
    BEGIN
        SELECT * INTO reg FROM relation_registry WHERE source_table = p_table LIMIT 1;
        IF NOT FOUND THEN
            RAISE EXCEPTION '% is not a registered relationship source', p_table
                USING ERRCODE = 'check_violation';
        END IF;
        IF reg.type_discriminator IS NULL THEN
            RETURN reg;
        END IF;
        v_value := upper(p_row ->> reg.type_discriminator);
        SELECT * INTO reg FROM relation_registry
         WHERE source_table = p_table AND type = v_value;
        IF FOUND THEN
            RETURN reg;
        END IF;
        SELECT * INTO reg FROM relation_registry WHERE source_table = p_table LIMIT 1;
        IF p_table = 'entity_links' AND v_value IN ('COMPARES_AGAINST', 'REPORTS_METRIC') THEN
            reg.type := v_value;
            reg.scope_policy := 'project_or_global';
            reg.projected := false;
            RETURN reg;
        END IF;
        RAISE EXCEPTION 'relationship type % of % is not registered', v_value, p_table
            USING ERRCODE = 'check_violation';
    END $$
    """,
    # Kind and scope of an endpoint. The row itself is an endpoint of HAS_VERSION and is
    # registered only after insert: use the scope its registration will give.
    """
    CREATE FUNCTION rp_endpoint(p_table text, p_row jsonb, p_uid uuid,
                                OUT o_kind text, OUT o_scope uuid, OUT o_found boolean)
    LANGUAGE plpgsql STABLE AS $$
    DECLARE
        src node_source_registry%ROWTYPE;
    BEGIN
        SELECT g.kind, g.scope_project_id INTO o_kind, o_scope FROM graph_nodes g
         WHERE g.uid = p_uid;
        o_found := o_kind IS NOT NULL;
        IF NOT o_found AND p_uid = (p_row ->> 'id')::uuid THEN
            SELECT * INTO src FROM node_source_registry WHERE source_table = p_table;
            IF src.source_table IS NOT NULL AND left(src.label, 1) <> '=' THEN
                o_kind := src.label;
                o_scope := CASE src.scope_rule
                    WHEN 'own_project_id' THEN (p_row ->> src.scope_column)::uuid
                    ELSE NULL END;
                o_found := true;
            END IF;
        END IF;
    END $$
    """,
    # BEFORE INSERT/UPDATE: allowed endpoint combination, identity, immutable endpoints.
    """
    CREATE FUNCTION rp_relation_check() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        new_row jsonb := to_jsonb(NEW);
        old_row jsonb;
        reg relation_registry%ROWTYPE;
        rule relation_endpoint_rules%ROWTYPE;
        parent graph_nodes%ROWTYPE;
        a record;
        b record;
        v_from uuid;
        v_to uuid;
        v_role text;
        v_uid uuid;
        exists_row boolean;
        patch jsonb := '{}'::jsonb;
    BEGIN
        IF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'structural_relations' THEN
            RAISE EXCEPTION 'structural relations are immutable (delete and re-create instead)'
                USING ERRCODE = 'check_violation';
        END IF;
        reg := rp_relation_spec(TG_TABLE_NAME, new_row);
        v_from := (new_row ->> reg.from_column)::uuid;
        v_to := (new_row ->> reg.to_column)::uuid;
        IF TG_OP = 'UPDATE' THEN
            old_row := to_jsonb(OLD);
            IF upper(coalesce(old_row ->> reg.type_discriminator, ''))
                   IS DISTINCT FROM upper(coalesce(new_row ->> reg.type_discriminator, ''))
               OR ((old_row ->> reg.from_column) IS DISTINCT FROM (new_row ->> reg.from_column)
                   OR (old_row ->> reg.to_column) IS DISTINCT FROM (new_row ->> reg.to_column))
                  AND TG_TABLE_NAME NOT IN ('paper_manifestations', 'project_items') THEN
                RAISE EXCEPTION 'the type and endpoints of a % relationship cannot change',
                    reg.type USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        v_role := CASE WHEN reg.type_discriminator = 'role' THEN ''
                       ELSE coalesce(new_row ->> 'role', '') END;

        -- A parent_project child (sub-question) is registered by its PART_OF link.
        IF TG_TABLE_NAME = 'structural_relations' THEN
            SELECT * INTO rule FROM relation_endpoint_rules
             WHERE type = reg.type AND from_kind = new_row ->> 'child_kind'
               AND to_kind = new_row ->> 'parent_kind' AND role = v_role;
            IF FOUND AND rule.child_table IS NOT NULL
               AND EXISTS (SELECT 1 FROM node_source_registry r
                           WHERE r.source_table = rule.child_table
                             AND r.scope_rule = 'parent_project')
               AND NOT EXISTS (SELECT 1 FROM graph_nodes WHERE uid = v_from) THEN
                SELECT * INTO parent FROM graph_nodes WHERE uid = v_to;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'parent node % does not exist', v_to
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
                EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I WHERE id = $1)',
                               rule.child_table) INTO exists_row USING v_from;
                IF NOT exists_row THEN
                    RAISE EXCEPTION 'child % does not exist in %', v_from, rule.child_table
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
                INSERT INTO graph_nodes (uid, kind, scope_project_id)
                VALUES (v_from, new_row ->> 'child_kind', parent.scope_project_id);
            END IF;
        END IF;

        SELECT * INTO a FROM rp_endpoint(TG_TABLE_NAME, new_row, v_from);
        SELECT * INTO b FROM rp_endpoint(TG_TABLE_NAME, new_row, v_to);
        IF NOT a.o_found OR NOT b.o_found THEN
            RAISE EXCEPTION '% endpoints must be registered graph nodes (% -> %)',
                reg.type, v_from, v_to USING ERRCODE = 'foreign_key_violation';
        END IF;
        IF reg.projected AND NOT EXISTS (
            SELECT 1 FROM relation_endpoint_rules
             WHERE type = reg.type AND role = v_role
               AND from_kind IN (a.o_kind, '*') AND to_kind IN (b.o_kind, '*')) THEN
            RAISE EXCEPTION '% from % to % (role %) is not an allowed combination',
                reg.type, a.o_kind, b.o_kind, coalesce(nullif(v_role, ''), '-')
                USING ERRCODE = 'check_violation';
        END IF;

        IF new_row ? 'relation_uid' THEN
            v_uid := rp_relation_uid(reg.type, TG_TABLE_NAME, v_from, v_to, '');
            IF TG_OP = 'INSERT' AND new_row ->> 'relation_uid' IS NOT NULL
               AND (new_row ->> 'relation_uid')::uuid <> v_uid THEN
                RAISE EXCEPTION 'relation_uid of % must be the deterministic edge id', reg.type
                    USING ERRCODE = 'check_violation';
            END IF;
            patch := patch || jsonb_build_object('relation_uid', v_uid);
        END IF;
        IF TG_OP = 'UPDATE' AND new_row ? 'updated_at' THEN
            patch := patch || jsonb_build_object('updated_at', now());
        END IF;
        IF patch <> '{}'::jsonb THEN
            NEW := jsonb_populate_record(NEW, patch);
        END IF;
        RETURN NEW;
    END $$
    """,
    # BEFORE INSERT/UPDATE: the project-scope invariant (§12.4.2a) for every source.
    f"""
    CREATE OR REPLACE FUNCTION enforce_relation_scope() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        new_row jsonb := to_jsonb(NEW);
        reg relation_registry%ROWTYPE;
        a record;
        b record;
        r_scope uuid;
    BEGIN
        reg := rp_relation_spec(TG_TABLE_NAME, new_row);
        SELECT * INTO a
          FROM rp_endpoint(TG_TABLE_NAME, new_row, (new_row ->> reg.from_column)::uuid);
        SELECT * INTO b
          FROM rp_endpoint(TG_TABLE_NAME, new_row, (new_row ->> reg.to_column)::uuid);
        IF NOT a.o_found OR NOT b.o_found THEN
            RAISE EXCEPTION '% endpoints must be registered graph nodes', reg.type
                USING ERRCODE = 'foreign_key_violation';
        END IF;
        r_scope := CASE WHEN reg.scope_column IS NULL THEN NULL
                        ELSE (new_row ->> reg.scope_column)::uuid END;
        IF a.o_scope IS NOT NULL AND b.o_scope IS NOT NULL AND a.o_scope <> b.o_scope THEN
            RAISE EXCEPTION '% may not connect nodes of different projects', reg.type
                USING ERRCODE = 'check_violation';
        END IF;
        IF coalesce(a.o_scope, b.o_scope) IS NOT NULL
           AND r_scope IS DISTINCT FROM coalesce(a.o_scope, b.o_scope) THEN
            RAISE EXCEPTION '% must carry the scope of its project-scoped endpoint', reg.type
                USING ERRCODE = 'check_violation';
        END IF;
        IF reg.scope_policy = 'project_only' AND r_scope IS NULL THEN
            RAISE EXCEPTION '% is project-only', reg.type USING ERRCODE = 'check_violation';
        END IF;
        IF reg.scope_policy = 'global_only' AND r_scope IS NOT NULL THEN
            RAISE EXCEPTION '% is global-only', reg.type USING ERRCODE = 'check_violation';
        END IF;
        -- Global-scope rule: global rows come only from global inputs.
        IF r_scope IS NULL AND new_row ? 'provenance' THEN
            IF coalesce((new_row -> 'provenance' ->> 'project_context')::boolean, false) THEN
                RAISE EXCEPTION 'a global % cannot be produced in a project context', reg.type
                    USING ERRCODE = 'check_violation';
            END IF;
            IF new_row ->> 'assertion' NOT IN ({ESTABLISHED}, 'rejected') THEN
                RAISE EXCEPTION 'a global % cannot have assertion %', reg.type,
                    new_row ->> 'assertion' USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END $$
    """,
    # Research relationships: evidence by assertion, sticky rejection, kept rejections.
    """
    CREATE FUNCTION rp_relation_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        r jsonb;
        o jsonb;
        ev jsonb;
        prov jsonb;
        v_assertion text;
        v_actor text := coalesce(current_setting('rp.actor', true), '');
        v_actor_scope text := coalesce(current_setting('rp.actor_scope', true), '');
        n_spans int;
        n_verified int;
    BEGIN
        IF TG_OP = 'DELETE' THEN
            -- Rejections are kept so they stay rejected; only cascades remove them.
            IF OLD.assertion = 'rejected' AND pg_trigger_depth() <= 1 THEN
                RAISE EXCEPTION 'rejected relationships are kept (%.%)', TG_TABLE_NAME,
                    coalesce(to_jsonb(OLD) ->> 'relation_uid', to_jsonb(OLD) ->> 'id')
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN OLD;
        END IF;
        r := to_jsonb(NEW);
        ev := coalesce(r -> 'evidence', '{}'::jsonb);
        prov := coalesce(r -> 'provenance', '{}'::jsonb);
        v_assertion := r ->> 'assertion';

        IF TG_OP = 'UPDATE' THEN
            o := to_jsonb(OLD);
            -- Sticky rejection: only a user acting in the row's project may change it.
            IF o ->> 'assertion' = 'rejected' AND r IS DISTINCT FROM o
               AND NOT (v_actor LIKE 'user:%' AND r ->> 'scope_project_id' IS NOT NULL
                        AND v_actor_scope = r ->> 'scope_project_id') THEN
                RAISE EXCEPTION 'a rejected relationship can only be changed by a user '
                    'in its project'
                    USING ERRCODE = 'check_violation';
            END IF;
            -- Global rows are rejected only by system verification, never by a user.
            IF r ->> 'scope_project_id' IS NULL AND v_assertion = 'rejected'
               AND o ->> 'assertion' <> 'rejected' AND v_actor NOT LIKE 'system:%' THEN
                RAISE EXCEPTION 'a global relationship is rejected only by system verification; '
                    'project decisions are overlays (relation_decisions)'
                    USING ERRCODE = 'check_violation';
            END IF;
        END IF;

        IF v_assertion = 'structural' THEN
            RAISE EXCEPTION 'research relationships cannot be structural'
                USING ERRCODE = 'check_violation';
        END IF;
        IF v_assertion IN ('source_metadata', 'user_asserted', 'user_confirmed')
           AND r ->> 'confidence' IS NOT NULL THEN
            RAISE EXCEPTION '% relationships carry no confidence', v_assertion
                USING ERRCODE = 'check_violation';
        END IF;

        IF v_assertion = 'source_metadata' THEN
            IF jsonb_array_length(coalesce(ev -> 'source_record_ids', '[]')) = 0
               OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(ev -> 'source_record_ids') s
                          WHERE NOT EXISTS (SELECT 1 FROM source_records sr
                                            WHERE sr.id = s::uuid)) THEN
                RAISE EXCEPTION 'source_metadata requires the source record(s) that reported it'
                    USING ERRCODE = 'check_violation';
            END IF;
        ELSIF v_assertion IN ('author_reported', 'extracted') THEN
            SELECT count(*), count(*) FILTER (WHERE e.verification IN ('exact', 'fuzzy'))
              INTO n_spans, n_verified
              FROM jsonb_array_elements_text(coalesce(ev -> 'span_ids', '[]')) s
              JOIN evidence_spans e ON e.id = s::uuid;
            IF n_verified = 0
               OR n_spans <> jsonb_array_length(coalesce(ev -> 'span_ids', '[]')) THEN
                RAISE EXCEPTION '% requires at least one verified evidence span', v_assertion
                    USING ERRCODE = 'check_violation';
            END IF;
        ELSIF v_assertion = 'computed' THEN
            IF NOT (jsonb_array_length(coalesce(ev -> 'signal_ids', '[]')) > 0
                    OR (coalesce(ev -> 'computation' ? 'method', false)
                        AND coalesce(ev -> 'computation' ? 'version', false))) THEN
                RAISE EXCEPTION 'computed requires a signal or computation reference'
                    USING ERRCODE = 'check_violation';
            END IF;
        ELSIF v_assertion = 'inferred' THEN
            IF r ->> 'confidence' IS NULL
               OR jsonb_array_length(coalesce(ev -> 'span_ids', '[]'))
                  + jsonb_array_length(coalesce(ev -> 'signal_ids', '[]')) = 0
               OR NOT (prov ? 'task' AND prov ? 'model') THEN
                RAISE EXCEPTION 'inferred requires confidence, evidence and the '
                    'producing task and model'
                    USING ERRCODE = 'check_violation';
            END IF;
        ELSIF v_assertion = 'hypothesized' THEN
            IF jsonb_array_length(coalesce(ev -> 'derived_from', '[]'))
               + jsonb_array_length(coalesce(ev -> 'span_ids', '[]')) = 0
               OR NOT (prov ? 'task' AND prov ? 'model') THEN
                RAISE EXCEPTION 'hypothesized requires its source and the producing '
                    'task and model'
                    USING ERRCODE = 'check_violation';
            END IF;
        ELSIF v_assertion IN ('user_asserted', 'user_confirmed') THEN
            IF NOT (prov ? 'actor' AND prov ? 'at') THEN
                RAISE EXCEPTION '% requires the acting user and time', v_assertion
                    USING ERRCODE = 'check_violation';
            END IF;
        ELSIF v_assertion = 'rejected' THEN
            IF NOT (prov ? 'rejected_by' AND prov ? 'rejection_reason') THEN
                RAISE EXCEPTION 'rejected requires who rejected it and why'
                    USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE FUNCTION rp_tombstone(p_uid uuid, p_kind text, p_reason text) RETURNS void
    LANGUAGE sql AS $$
        INSERT INTO entity_tombstones (uid, kind, reason)
        VALUES (p_uid, p_kind, p_reason)
        ON CONFLICT (uid) DO UPDATE SET kind = EXCLUDED.kind, reason = EXCLUDED.reason,
            deleted_at = now(), purge_after = now() + interval '30 days',
            graph_removed_at = NULL, verified_absent_at = NULL, attempts = 0
    $$
    """,
    """
    CREATE FUNCTION rp_deletion_reason(p_default text) RETURNS text LANGUAGE sql STABLE AS $$
        SELECT coalesce(nullif(current_setting('rp.deletion_reason', true), ''), p_default)
    $$
    """,
    # AFTER: deletion markers for removed, moved, rejected or retracted edges; assertion log.
    """
    CREATE FUNCTION rp_relation_after() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        reg relation_registry%ROWTYPE;
        r jsonb;
        o jsonb;
        v_uid uuid;
        v_old_uid uuid;
    BEGIN
        IF TG_OP = 'DELETE' THEN
            o := to_jsonb(OLD);
            reg := rp_relation_spec(TG_TABLE_NAME, o);
            IF reg.projected THEN
                PERFORM rp_tombstone(coalesce((o ->> 'relation_uid')::uuid, (o ->> 'id')::uuid),
                                     reg.type, rp_deletion_reason('user_delete'));
            END IF;
            RETURN OLD;
        END IF;
        r := to_jsonb(NEW);
        reg := rp_relation_spec(TG_TABLE_NAME, r);
        v_uid := coalesce((r ->> 'relation_uid')::uuid, (r ->> 'id')::uuid);
        IF TG_OP = 'INSERT' THEN
            DELETE FROM entity_tombstones WHERE uid = v_uid;  -- the edge exists again
            RETURN NEW;
        END IF;
        o := to_jsonb(OLD);
        v_old_uid := coalesce((o ->> 'relation_uid')::uuid, (o ->> 'id')::uuid);
        IF v_old_uid <> v_uid AND reg.projected THEN
            PERFORM rp_tombstone(v_old_uid, reg.type, rp_deletion_reason('merge_split'));
            DELETE FROM entity_tombstones WHERE uid = v_uid;
        END IF;
        IF o ? 'assertion' AND (o ->> 'assertion' IS DISTINCT FROM r ->> 'assertion'
                                OR o ->> 'status' IS DISTINCT FROM r ->> 'status') THEN
            INSERT INTO relation_assertion_log (relation_table, relation_uid, from_assertion,
                to_assertion, from_status, to_status, reason, actor, scope_project_id)
            VALUES (TG_TABLE_NAME, v_uid, o ->> 'assertion', r ->> 'assertion',
                    o ->> 'status', r ->> 'status',
                    nullif(current_setting('rp.change_reason', true), ''),
                    nullif(current_setting('rp.actor', true), ''),
                    (r ->> 'scope_project_id')::uuid);
            IF reg.projected THEN
                IF r ->> 'assertion' = 'rejected' THEN
                    PERFORM rp_tombstone(v_uid, reg.type, 'rejected');
                ELSIF r ->> 'status' = 'retracted' THEN
                    PERFORM rp_tombstone(v_uid, reg.type, 'retracted');
                ELSE
                    DELETE FROM entity_tombstones WHERE uid = v_uid;  -- eligible again
                END IF;
            END IF;
        END IF;
        RETURN NEW;
    END $$
    """,
    # Every removed graph node leaves a marker; a re-registered uid clears it.
    """
    CREATE FUNCTION rp_graph_node_marker() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            PERFORM rp_tombstone(OLD.uid, OLD.kind, rp_deletion_reason('user_delete'));
            RETURN OLD;
        END IF;
        DELETE FROM entity_tombstones WHERE uid = NEW.uid;
        RETURN NEW;
    END $$
    """,
    # Deleting a project or an account sets the reason for the markers its cascade writes.
    """
    CREATE FUNCTION rp_set_deletion_reason() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF coalesce(current_setting('rp.deletion_reason', true), '') = '' THEN
            PERFORM set_config('rp.deletion_reason', TG_ARGV[0], true);
        END IF;
        RETURN OLD;
    END $$
    """,
    """
    CREATE FUNCTION rp_attach_relation_source(p_table text, p_research boolean)
    RETURNS void LANGUAGE plpgsql AS $$
    BEGIN
        EXECUTE format('CREATE TRIGGER rp_relation_10_check BEFORE INSERT OR UPDATE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION rp_relation_check()', p_table);
        EXECUTE format('CREATE TRIGGER rp_relation_20_scope BEFORE INSERT OR UPDATE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION enforce_relation_scope()', p_table);
        IF p_research THEN
            EXECUTE format('CREATE TRIGGER rp_relation_30_evidence BEFORE INSERT OR UPDATE OR '
                           'DELETE ON %I FOR EACH ROW EXECUTE FUNCTION rp_relation_evidence()',
                           p_table);
        END IF;
        EXECUTE format('CREATE TRIGGER rp_relation_40_after AFTER INSERT OR UPDATE OR DELETE '
                       'ON %I FOR EACH ROW EXECUTE FUNCTION rp_relation_after()', p_table);
    END $$
    """,
    """
    CREATE FUNCTION rp_detach_relation_source(p_table text) RETURNS void LANGUAGE plpgsql AS $$
    BEGIN
        EXECUTE format('DROP TRIGGER IF EXISTS rp_relation_10_check ON %I', p_table);
        EXECUTE format('DROP TRIGGER IF EXISTS rp_relation_20_scope ON %I', p_table);
        EXECUTE format('DROP TRIGGER IF EXISTS rp_relation_30_evidence ON %I', p_table);
        EXECUTE format('DROP TRIGGER IF EXISTS rp_relation_40_after ON %I', p_table);
    END $$
    """,
]

RESEARCH_TABLES = (
    "citations",
    "paper_authors",
    "author_affiliations",
    "entity_links",
    "research_relations",
)
STRUCTURAL_TABLES = ("paper_manifestations", "project_items", "structural_relations")

TRIGGERS = [
    # 0008's structural-only endpoint trigger is replaced by the generic one.
    "DROP TRIGGER rp_relation_10_endpoints ON structural_relations",
    "DROP TRIGGER rp_relation_20_scope ON structural_relations",
    "DROP FUNCTION rp_relation_endpoints()",
    *[f"SELECT rp_attach_relation_source('{t}', true)" for t in RESEARCH_TABLES],
    *[f"SELECT rp_attach_relation_source('{t}', false)" for t in STRUCTURAL_TABLES],
    *[
        f"CREATE TRIGGER rp_bump_row_version BEFORE UPDATE ON {t} "
        "FOR EACH ROW EXECUTE FUNCTION rp_bump_row_version()"
        for t in (*RESEARCH_TABLES, "project_items")
    ],
    "CREATE TRIGGER rp_graph_node_marker AFTER INSERT OR DELETE ON graph_nodes "
    "FOR EACH ROW EXECUTE FUNCTION rp_graph_node_marker()",
    "CREATE TRIGGER rp_set_deletion_reason BEFORE DELETE ON projects "
    "FOR EACH ROW EXECUTE FUNCTION rp_set_deletion_reason('project_delete')",
    "CREATE TRIGGER rp_set_deletion_reason BEFORE DELETE ON users "
    "FOR EACH ROW EXECUTE FUNCTION rp_set_deletion_reason('account_delete')",
]

DOWN = [
    "DROP TRIGGER IF EXISTS rp_set_deletion_reason ON users",
    "DROP TRIGGER IF EXISTS rp_set_deletion_reason ON projects",
    "DROP TRIGGER IF EXISTS rp_graph_node_marker ON graph_nodes",
    *[f"DROP TRIGGER IF EXISTS rp_bump_row_version ON {t}" for t in ("project_items",)],
    *[f"SELECT rp_detach_relation_source('{t}')" for t in (*RESEARCH_TABLES, *STRUCTURAL_TABLES)],
    "DROP FUNCTION IF EXISTS rp_detach_relation_source(text)",
    "DROP FUNCTION IF EXISTS rp_attach_relation_source(text, boolean)",
    "DROP FUNCTION IF EXISTS rp_set_deletion_reason()",
    "DROP FUNCTION IF EXISTS rp_graph_node_marker()",
    "DROP FUNCTION IF EXISTS rp_relation_after()",
    "DROP FUNCTION IF EXISTS rp_deletion_reason(text)",
    "DROP FUNCTION IF EXISTS rp_tombstone(uuid, text, text)",
    "DROP FUNCTION IF EXISTS rp_relation_evidence()",
    "DROP FUNCTION IF EXISTS rp_relation_check()",
    "DROP FUNCTION IF EXISTS rp_endpoint(text, jsonb, uuid)",
    "DROP FUNCTION IF EXISTS rp_relation_spec(text, jsonb)",
    "DROP FUNCTION IF EXISTS rp_relation_uid(text, text, uuid, uuid, text)",
    "DELETE FROM relation_endpoint_rules WHERE type <> 'PART_OF'",
    "DELETE FROM relation_registry WHERE type <> 'PART_OF'",
    "SELECT rp_detach_node_source('entities')",
    "SELECT rp_detach_node_source('research_groups')",
    "SELECT rp_detach_node_source('authors')",
    "DELETE FROM graph_nodes WHERE kind IN ('Author', 'ResearchGroup', 'Method', 'Dataset', "
    "'Benchmark', 'Metric', 'Model') OR (kind = 'Topic' AND uid IN (SELECT id FROM entities))",
    "DROP FUNCTION IF EXISTS rp_entity_label(text)",
]
