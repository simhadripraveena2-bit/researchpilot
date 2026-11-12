"""Integrity audits of the graph-ready schema (R1-65, ARCHITECTURE §12.4.2-12.4.3).

* ``check_enforcement``: every registered relationship source has its triggers, endpoint and
  scope columns with foreign keys, the global-only CHECK, and matches the code registry.
* ``undeclared_references``: reference columns into node tables that are neither registered
  relationship columns nor declared non-sources (hidden second sources).
* ``find_orphans``: graph nodes without a source row, qualifying rows without a node, and
  nodes whose kind or scope disagrees with their source row.

All read-only; used by tests and runnable against any database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.domain.enums import ItemType, RelationClass, ScopePolicy
from researchpilot.relations import registry

_REQUIRED_TRIGGERS = ("rp_relation_10_check", "rp_relation_20_scope", "rp_relation_40_after")
_SCOPE_COLUMNS = frozenset({"project_id", "scope_project_id"})
_SCOPE_TARGETS = frozenset({"projects", "research_objectives"})


async def check_enforcement(session: AsyncSession) -> list[str]:
    problems: list[str] = []
    rows = (await session.execute(sa.text("SELECT * FROM relation_registry"))).mappings().all()
    db_types = {r["type"] for r in rows}
    code_types = {s.type for s in registry.AVAILABLE}
    if db_types != code_types:
        problems.append(
            f"registry mismatch: only in database {sorted(db_types - code_types)}, "
            f"only in code {sorted(code_types - db_types)}"
        )
    for r in rows:
        problems += await _check_row(session, r)
    return problems


async def _check_row(session: AsyncSession, r: sa.RowMapping) -> list[str]:
    t, table = r["type"], r["source_table"]
    out: list[str] = []
    spec = registry.BY_TYPE.get(t)
    if spec is not None and (
        spec.source_table != table
        or spec.from_column != r["from_column"]
        or spec.to_column != r["to_column"]
        or spec.scope_column != r["scope_column"]
        or spec.scope_policy.value != r["scope_policy"]
        or spec.relation_class.value != r["class"]
        or spec.type_discriminator != r["type_discriminator"]
    ):
        out.append(f"{t}: code registry and database registry differ")
    columns = set(
        (
            await session.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t"
                ),
                {"t": table},
            )
        ).scalars()
    )
    if not columns:
        return [*out, f"{t}: source table {table} does not exist"]
    triggers = set(
        (
            await session.execute(
                sa.text(
                    "SELECT t.tgname FROM pg_trigger t WHERE t.tgrelid = CAST(:t AS regclass) "
                    "AND NOT t.tgisinternal"
                ),
                {"t": table},
            )
        ).scalars()
    )
    required = list(_REQUIRED_TRIGGERS)
    if r["class"] == RelationClass.RESEARCH.value:
        required.append("rp_relation_30_evidence")
    out += [f"{t}: {table} lacks trigger {name}" for name in required if name not in triggers]
    fk_columns = await _fk_columns(session, table)
    for role in ("from_column", "to_column"):
        column = r[role]
        if column not in columns:
            out.append(f"{t}: {table}.{column} does not exist")
        elif column != "id" and column not in fk_columns:
            out.append(f"{t}: {table}.{column} has no foreign key")
    scope = r["scope_column"]
    if scope is None:
        if r["scope_policy"] != ScopePolicy.GLOBAL_ONLY.value:
            out.append(f"{t}: a source without a scope column must be global_only")
    else:
        if scope not in columns:
            out.append(f"{t}: scope column {table}.{scope} does not exist")
        elif fk_columns.get(scope) != "projects":
            out.append(f"{t}: {table}.{scope} must reference projects")
        if r["scope_policy"] == ScopePolicy.GLOBAL_ONLY.value and scope == "scope_project_id":
            has_check = await session.scalar(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE contype = 'c' "
                    "AND conrelid = CAST(:t AS regclass) "
                    "AND pg_get_constraintdef(oid) ILIKE '%scope_project_id IS NULL%')"
                ),
                {"t": table},
            )
            if not has_check:
                out.append(f"{t}: global-only {table} lacks CHECK (scope_project_id IS NULL)")
    return out


async def _fk_columns(session: AsyncSession, table: str) -> dict[str, str]:
    """Column -> referenced table, for every column taking part in a foreign key."""
    rows = await session.execute(
        sa.text(
            "SELECT a.attname, c.confrelid::regclass::text FROM pg_constraint c "
            "JOIN LATERAL unnest(c.conkey) k(attnum) ON true "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum "
            "WHERE c.contype = 'f' AND c.conrelid = CAST(:t AS regclass)"
        ),
        {"t": table},
    )
    out: dict[str, str] = {}
    for column, target in rows:
        out.setdefault(column, target)
        if target == "projects":
            out[column] = target
    return out


async def undeclared_references(session: AsyncSession) -> list[str]:
    """R1-65 (c)/(d): reference columns into node tables must be registered relationship
    columns, access-control scope, or declared non-sources."""
    node_tables = set(
        (await session.execute(sa.text("SELECT source_table FROM node_source_registry"))).scalars()
    ) | {"research_items"}
    registered: set[str] = set()
    for spec in registry.SPECS:
        for column in (spec.from_column, spec.to_column, spec.source_column, spec.scope_column):
            if column:
                registered.add(f"{spec.source_table}.{column}")
    relation_tables = {s.source_table for s in registry.SPECS}
    rows = await session.execute(
        sa.text(
            "SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text "
            "FROM pg_constraint c JOIN LATERAL unnest(c.conkey) WITH ORDINALITY k(attnum, n) "
            "ON k.n = 1 JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum "
            "WHERE c.contype = 'f'"
        )
    )
    problems = []
    for table, column, target in rows:
        name = f"{table}.{column}"
        if target == "graph_nodes":
            if table not in relation_tables:
                problems.append(f"{name} links graph nodes but is not a relationship source")
            continue
        if target not in node_tables:
            continue
        if column in _SCOPE_COLUMNS and target in _SCOPE_TARGETS:
            continue
        if name in registered or name in registry.DECLARED_NON_SOURCES:
            continue
        problems.append(f"{name} -> {target} is neither a relationship source nor declared")
    return problems


@dataclass(frozen=True)
class Orphan:
    uid: uuid.UUID
    kind: str
    problem: str  # no_source_row | missing_node | scope_mismatch | kind_mismatch


async def find_orphans(session: AsyncSession) -> list[Orphan]:
    sources = (
        (await session.execute(sa.text("SELECT * FROM node_source_registry"))).mappings().all()
    )
    found: list[Orphan] = []
    # Which tables can hold a node of each kind.
    tables_by_kind: dict[str, list[str]] = {}
    for s in sources:
        label = s["label"]
        if label.startswith("="):
            # Expression labels (entities) depend on ``type``: evaluate them for every type.
            kinds = set(
                (
                    await session.execute(
                        sa.text(
                            f"SELECT DISTINCT {label[1:]} FROM "  # noqa: S608
                            "(SELECT unnest(CAST(:types AS text[])) AS type) r"
                        ),
                        {"types": [t.value for t in ItemType]},
                    )
                ).scalars()
            )
        else:
            kinds = {label}
        for kind in kinds:
            if kind:
                tables_by_kind.setdefault(kind, []).append(s["source_table"])
    graph_kinds = set(
        (await session.execute(sa.text("SELECT DISTINCT kind FROM graph_nodes"))).scalars()
    )
    for kind in graph_kinds:
        tables = tables_by_kind.get(kind, [])
        exists = (
            " OR ".join(
                f"EXISTS (SELECT 1 FROM {t} WHERE id = g.uid)"  # noqa: S608
                for t in tables
            )
            or "false"
        )
        for (uid,) in await session.execute(
            sa.text(f"SELECT g.uid FROM graph_nodes g WHERE g.kind = :k AND NOT ({exists})"),  # noqa: S608
            {"k": kind},
        ):
            found.append(Orphan(uid, kind, "no_source_row"))

    for s in sources:
        table, label, rule = s["source_table"], s["label"], s["scope_rule"]
        condition = s["registration_condition"] or "true"
        kind_expr = label[1:] if label.startswith("=") else f"'{label}'"
        if rule == "global":
            scope_expr = "NULL::uuid"
        elif rule == "own_project_id":
            scope_expr = f"r.{s['scope_column']}"
        elif rule == "self":
            scope_expr = "r.id"
        else:  # parent_project: the scope of the parent it is PART_OF
            scope_expr = (
                "(SELECT p.scope_project_id FROM structural_relations sr JOIN graph_nodes p "
                "ON p.uid = sr.parent_uid WHERE sr.child_uid = r.id AND sr.type = 'PART_OF' "
                "LIMIT 1)"
            )
        query = (
            f"SELECT r.id, ({kind_expr}) AS kind, g.uid AS node, g.kind AS node_kind, "  # noqa: S608
            f"g.scope_project_id AS node_scope, {scope_expr} AS scope "
            f"FROM (SELECT * FROM {table} WHERE {condition}) r "
            "LEFT JOIN graph_nodes g ON g.uid = r.id"
        )
        for row in (await session.execute(sa.text(query))).mappings():
            if row["node"] is None:
                found.append(Orphan(row["id"], row["kind"], "missing_node"))
            elif row["node_kind"] != row["kind"]:
                found.append(Orphan(row["id"], row["node_kind"], "kind_mismatch"))
            elif row["node_scope"] != row["scope"]:
                found.append(Orphan(row["id"], row["node_kind"], "scope_mismatch"))
    return found
