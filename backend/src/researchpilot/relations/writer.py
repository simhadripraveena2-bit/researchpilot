"""RelationWriter: the only code that writes relationship rows (ARCHITECTURE §12.5).

Callers say which scope they act in (``WriteContext``); the writer never decides scope.
It validates before writing (clear errors instead of database exceptions) and the database
re-checks everything (endpoints, scope, evidence, sticky rejection) for any writer.

* Natural keys: a re-extraction finds the existing row, so a rejected relationship is never
  created twice; an automatic write that hits it is a logged no-op ("suppressed").
* Never a downgrade: an automatic write does not replace a stronger assertion (a user's,
  or an established one by an inferred one).
* Decisions on *global* rows are project overlays (``relation_decisions``) plus a
  suppression; the global row is unchanged. Decisions on project rows change the row.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.core.errors import NotFound, ValidationFailed
from researchpilot.core.ids import uuid7
from researchpilot.core.logging import get_logger
from researchpilot.domain.enums import (
    GLOBAL_ASSERTIONS,
    USER_ASSERTIONS,
    Assertion,
    AssertionChangeReason,
    DiscoveredVia,
    RelationDecisionKind,
    RelationStatus,
    ScopePolicy,
    TombstoneReason,
)
from researchpilot.relations import registry
from researchpilot.relations.ids import fingerprint
from researchpilot.relations.registry import RelationSpec

log = get_logger(component="relations")


class RelationRejected(ValidationFailed):
    code = "relation_rejected"


# --- inputs -------------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Computation(_Strict):
    method: str
    version: str
    inputs: list[str] = []


class Evidence(_Strict):
    """References only (no content): spans, source records, signals, computations, sources."""

    span_ids: list[uuid.UUID] = []
    source_record_ids: list[uuid.UUID] = []
    signal_ids: list[uuid.UUID] = []
    computation: Computation | None = None
    derived_from: list[uuid.UUID] = []

    def as_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_defaults=True)


class Provenance(_Strict):
    """What produced the relationship. The writer adds project_context, actor and time."""

    service: str
    service_version: str | None = None
    task: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    source_api: str | None = None


class NewRelation(_Strict):
    type: str
    from_uid: uuid.UUID
    to_uid: uuid.UUID
    assertion: Assertion
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: Evidence = Evidence()
    provenance: Provenance
    properties: dict[str, Any] = {}
    # Text whose normalised hash identifies near-duplicates (e.g. a limitation's wording).
    fingerprint_text: str | None = None

    @field_validator("type")
    @classmethod
    def _known(cls, v: str) -> str:
        spec = registry.BY_TYPE.get(v)
        if spec is None:
            raise ValueError(f"unknown relationship type {v!r}")
        if not spec.available:
            raise ValueError(f"{v} arrives in {spec.introduced_in} (its source does not exist yet)")
        return v


@dataclass(frozen=True)
class Actor:
    kind: Literal["system", "user"]
    id: str

    def __str__(self) -> str:
        return f"{self.kind}:{self.id}"


@dataclass(frozen=True)
class WriteContext:
    """Who writes, in which scope. ``project_id`` None = global context (global inputs only)."""

    project_id: uuid.UUID | None
    actor: Actor

    @classmethod
    def system(cls, service: str, project_id: uuid.UUID | None = None) -> WriteContext:
        return cls(project_id, Actor("system", service))

    @classmethod
    def user(cls, user_id: uuid.UUID, project_id: uuid.UUID) -> WriteContext:
        return cls(project_id, Actor("user", str(user_id)))

    @property
    def is_user(self) -> bool:
        return self.actor.kind == "user"


class Outcome(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    SUPPRESSED = "suppressed"


@dataclass(frozen=True)
class WriteResult:
    uid: uuid.UUID | None
    outcome: Outcome
    table: str


@dataclass(frozen=True)
class StoredRelation:
    table: str
    uid: uuid.UUID
    type: str
    from_uid: uuid.UUID
    to_uid: uuid.UUID
    assertion: Assertion
    status: RelationStatus
    scope_project_id: uuid.UUID | None
    confidence: float | None
    evidence: dict[str, Any]
    provenance: dict[str, Any]


# Strength of assertions: automatic writes never replace a stronger one.
_RANK = {
    Assertion.HYPOTHESIZED: 1,
    Assertion.INFERRED: 2,
    Assertion.COMPUTED: 3,
    Assertion.SOURCE_METADATA: 3,
    Assertion.EXTRACTED: 3,
    Assertion.AUTHOR_REPORTED: 3,
    Assertion.USER_ASSERTED: 4,
    Assertion.USER_CONFIRMED: 4,
}
_NO_CONFIDENCE = USER_ASSERTIONS | {Assertion.SOURCE_METADATA}


# --- table mapping ------------------------------------------------------------------------


@dataclass(frozen=True)
class _Row:
    table: str
    uid_column: str
    key: dict[str, Any]
    values: dict[str, Any]


_TYPED_PROPERTIES: dict[str, frozenset[str]] = {
    "citations": frozenset({"sources", "is_influential", "intents", "contexts"}),
    "paper_authors": frozenset({"position", "raw_name", "raw_affiliations"}),
    "author_affiliations": frozenset({"paper_id", "raw_affiliation", "period"}),
    "entity_links": frozenset({"manifestation_id", "extraction_run_id"}),
}
_JSON_COLUMNS = frozenset(
    {"evidence", "provenance", "properties", "contexts", "raw_affiliations", "period"}
)


def _row(
    spec: RelationSpec,
    rel: NewRelation,
    scope: uuid.UUID | None,
    from_kind: str,
    to_kind: str,
) -> _Row:
    props = dict(rel.properties)
    table = spec.source_table
    if table in _TYPED_PROPERTIES:
        unknown = set(props) - _TYPED_PROPERTIES[table]
        if unknown:
            raise RelationRejected(f"{rel.type} has no properties {sorted(unknown)}")
    a, b = rel.from_uid, rel.to_uid
    if table == "citations":
        return _Row(table, "relation_uid", {"citing_id": a, "cited_id": b}, props)
    if table == "paper_authors":
        return _Row(table, "relation_uid", {"paper_id": a, "author_id": b}, props)
    if table == "author_affiliations":
        paper = props.pop("paper_id", None)
        key = {"author_id": a, "group_id": b, "paper_id": paper}
        return _Row(table, "id", key, props)
    if table == "entity_links":
        key = {
            "subject_uid": a,
            "entity_id": b,
            "role": spec.discriminator_value,
            "scope_project_id": scope,
        }
        return _Row(table, "id", key, {"subject_kind": from_kind, **props})
    if table == "research_relations":
        qualifier = str(props.get("qualifier") or "")
        key = {
            "type": rel.type,
            "from_uid": a,
            "to_uid": b,
            "qualifier": qualifier,
            "scope_project_id": scope,
        }
        values = {"from_kind": from_kind, "to_kind": to_kind, "properties": props}
        return _Row(table, "id", key, values)
    raise RelationRejected(f"{rel.type} is not written through write()")  # pragma: no cover


def _param(column: str, value: Any) -> tuple[str, Any]:
    if column in _JSON_COLUMNS:
        return f"CAST(:{column} AS jsonb)", json.dumps(value, default=str)
    return f":{column}", value


@asynccontextmanager
async def _settings(session: AsyncSession, **values: str) -> AsyncIterator[None]:
    """Transaction-local settings read by the triggers (actor, scope, reasons); reset after."""
    for name, value in values.items():
        await session.execute(
            sa.text("SELECT set_config(:n, :v, true)"), {"n": f"rp.{name}", "v": value}
        )
    try:
        yield
    finally:
        for name in values:
            await session.execute(sa.text("SELECT set_config(:n, '', true)"), {"n": f"rp.{name}"})


# --- the writer ---------------------------------------------------------------------------


class RelationWriter:
    """Stateless; one instance can serve every request."""

    # Research relationships ------------------------------------------------------------

    async def write(
        self, session: AsyncSession, ctx: WriteContext, rel: NewRelation
    ) -> WriteResult:
        spec = registry.BY_TYPE[rel.type]
        if not spec.is_research:
            raise RelationRejected(f"{rel.type} is structural; use its dedicated method")
        scope = ctx.project_id
        from_kind, to_kind = await self._check_endpoints(session, spec, rel, scope)
        self._check_assertion(ctx, rel, scope)
        await self._check_evidence(session, rel)

        provenance: dict[str, Any] = {
            **rel.provenance.model_dump(exclude_none=True),
            "project_context": scope is not None,
            "actor": str(ctx.actor),
            "at": datetime.now(UTC).isoformat(),
        }
        fp = fingerprint(rel.type, rel.from_uid, rel.to_uid, rel.fingerprint_text)
        if rel.fingerprint_text:
            provenance["fingerprint"] = fp
        row = _row(spec, rel, scope, from_kind, to_kind)
        values = {
            **row.values,
            "assertion": rel.assertion.value,
            "confidence": rel.confidence,
            "evidence": rel.evidence.as_json(),
            "provenance": provenance,
            "scope_project_id": scope,
        }

        existing = await self._find(session, row)
        if existing is not None:
            return await self._update_existing(session, ctx, spec, row, existing, values)
        if not ctx.is_user and await self._suppressed(session, rel, scope, fp):
            return self._suppress(spec, None, "matches a rejected relationship")
        # ``qualifier`` is generated from properties (research_relations).
        columns = {k: v for k, v in {**row.key, **values}.items() if k != "qualifier"}
        names = ", ".join(columns)
        placeholders, params = [], {}
        for column, value in columns.items():
            placeholder, params[column] = _param(column, value)
            placeholders.append(placeholder)
        if row.uid_column == "id":
            names += ", id"
            placeholders.append(":id")
            params["id"] = uuid7()
        inserted = await session.scalar(
            sa.text(
                f"INSERT INTO {row.table} ({names}) VALUES ({', '.join(placeholders)}) "  # noqa: S608
                f"ON CONFLICT DO NOTHING RETURNING {row.uid_column}"
            ),
            params,
        )
        if inserted is None:  # a concurrent writer created it first
            existing = await self._find(session, row)
            assert existing is not None
            return await self._update_existing(session, ctx, spec, row, existing, values)
        return WriteResult(inserted, Outcome.CREATED, row.table)

    async def _update_existing(
        self,
        session: AsyncSession,
        ctx: WriteContext,
        spec: RelationSpec,
        row: _Row,
        existing: Mapping[str, Any],
        values: dict[str, Any],
    ) -> WriteResult:
        uid = existing["uid"]
        old = Assertion(existing["assertion"])
        new = Assertion(values["assertion"])
        in_scope_user = ctx.is_user and existing["scope_project_id"] == ctx.project_id
        if old is Assertion.REJECTED or existing["status"] == RelationStatus.RETRACTED.value:
            if not (in_scope_user and new in USER_ASSERTIONS):
                return self._suppress(spec, uid, f"existing row is {old.value}")
            reason = AssertionChangeReason.USER_RESTORED
        elif _RANK[new] < _RANK[old] or (old in USER_ASSERTIONS and not ctx.is_user):
            return WriteResult(uid, Outcome.UNCHANGED, row.table)
        elif _RANK[old] <= 2 and _RANK[new] == 3 and values["evidence"].get("span_ids"):
            reason = AssertionChangeReason.QUOTE_VERIFIED
        elif new is Assertion.USER_CONFIRMED and old is not new:
            reason = AssertionChangeReason.USER_CONFIRMED
        else:
            reason = None
        comparable = {k: v for k, v in values.items() if k != "provenance"}
        if all(_same(existing.get(k), v) for k, v in comparable.items()) and reason is None:
            return WriteResult(uid, Outcome.UNCHANGED, row.table)
        updates = {k: v for k, v in values.items() if k not in row.key}
        if existing["status"] == RelationStatus.RETRACTED.value:
            updates["status"] = RelationStatus.ACTIVE.value
        await self._apply(session, ctx, row.table, row.uid_column, uid, updates, reason)
        return WriteResult(uid, Outcome.UPDATED, row.table)

    # Decisions ---------------------------------------------------------------------------

    async def reject(
        self, session: AsyncSession, ctx: WriteContext, uid: uuid.UUID, reason: str
    ) -> StoredRelation:
        """A user rejects a relationship in their project. Project rows become ``rejected``
        (sticky); global rows get a project overlay. Both get a suppression in the project."""
        if not ctx.is_user or ctx.project_id is None:
            raise RelationRejected("only a user acting in a project can reject a relationship")
        rel = await self._visible(session, ctx, uid)
        if rel.scope_project_id is None:
            await self._decide(session, ctx, rel, RelationDecisionKind.REJECTED, reason)
        elif rel.assertion is not Assertion.REJECTED:
            provenance = {
                **rel.provenance,
                "rejected_by": str(ctx.actor),
                "rejection_reason": reason,
                "rejected_at": datetime.now(UTC).isoformat(),
            }
            await self._apply(
                session,
                ctx,
                rel.table,
                _uid_column(rel.table),
                rel.uid,
                {"assertion": Assertion.REJECTED.value, "provenance": provenance},
                AssertionChangeReason.USER_REJECTED,
            )
        await self._add_suppression(session, rel, ctx, reason)
        return await self.get(session, rel.uid)

    async def confirm(
        self, session: AsyncSession, ctx: WriteContext, uid: uuid.UUID
    ) -> StoredRelation:
        """A user confirms a relationship: project rows become ``user_confirmed`` (also from
        rejected); global rows get a project overlay and stay unchanged."""
        if not ctx.is_user or ctx.project_id is None:
            raise RelationRejected("only a user acting in a project can confirm a relationship")
        rel = await self._visible(session, ctx, uid)
        if rel.scope_project_id is None:
            await self._decide(session, ctx, rel, RelationDecisionKind.CONFIRMED, None)
            return rel
        provenance = {
            **{k: v for k, v in rel.provenance.items() if not k.startswith("rejected")},
            "actor": str(ctx.actor),
            "at": datetime.now(UTC).isoformat(),
            "confirmed_from": rel.assertion.value,
            "prior_confidence": rel.confidence,
        }
        await self._apply(
            session,
            ctx,
            rel.table,
            _uid_column(rel.table),
            rel.uid,
            {
                "assertion": Assertion.USER_CONFIRMED.value,
                "confidence": None,
                "provenance": provenance,
                "status": RelationStatus.ACTIVE.value,
            },
            AssertionChangeReason.USER_CONFIRMED,
        )
        await session.execute(
            sa.text(
                "DELETE FROM relation_suppressions WHERE type = :t AND from_uid = :a "
                "AND (to_uid IS NULL OR to_uid = :b) AND scope_project_id = :p"
            ),
            {"t": rel.type, "a": rel.from_uid, "b": rel.to_uid, "p": ctx.project_id},
        )
        return await self.get(session, rel.uid)

    async def system_reject(
        self, session: AsyncSession, uid: uuid.UUID, service: str, reason: str
    ) -> StoredRelation:
        """Verification failed (e.g. the quote is not in the paper): any scope, sticky."""
        rel = await self.get(session, uid)
        ctx = WriteContext.system(service, rel.scope_project_id)
        provenance = {
            **rel.provenance,
            "rejected_by": str(ctx.actor),
            "rejection_reason": reason,
        }
        await self._apply(
            session,
            ctx,
            rel.table,
            _uid_column(rel.table),
            rel.uid,
            {"assertion": Assertion.REJECTED.value, "provenance": provenance},
            AssertionChangeReason.VERIFICATION_FAILED,
        )
        await self._add_suppression(session, rel, ctx, reason)
        return await self.get(session, uid)

    async def retract(self, session: AsyncSession, uid: uuid.UUID, service: str) -> None:
        """The source withdrew it or it was superseded: kept, but no longer active."""
        rel = await self.get(session, uid)
        ctx = WriteContext.system(service, rel.scope_project_id)
        await self._apply(
            session,
            ctx,
            rel.table,
            _uid_column(rel.table),
            rel.uid,
            {"status": RelationStatus.RETRACTED.value},
            AssertionChangeReason.SOURCE_RETRACTED,
        )

    # Structural relationships ------------------------------------------------------------

    async def link_part_of(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
        child: tuple[uuid.UUID, str],
        parent: tuple[uuid.UUID, str],
    ) -> uuid.UUID:
        """PART_OF (composition): e.g. a sub-question of an objective version."""
        rel_id = uuid7()
        await session.execute(
            sa.text(
                "INSERT INTO structural_relations (id, type, child_uid, child_kind, parent_uid, "
                "parent_kind, scope_project_id) VALUES (:id, 'PART_OF', :c, :ck, :p, :pk, :s)"
            ),
            {
                "id": rel_id,
                "c": child[0],
                "ck": child[1],
                "p": parent[0],
                "pk": parent[1],
                "s": project_id,
            },
        )
        return rel_id

    async def add_to_project(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        discovered_via: DiscoveredVia,
        *,
        run_id: uuid.UUID | None = None,
        from_item_id: uuid.UUID | None = None,
        objective_version: int | None = None,
    ) -> bool:
        """IN_PROJECT. Records the objective version it was found with (kept for good): the
        run's version when given, otherwise the project's active version. False if the item
        was already in the project (its original record is unchanged)."""
        added = await session.scalar(
            sa.text(
                "INSERT INTO project_items (project_id, item_id, discovered_via, "
                "discovered_in_run_id, discovered_from_item_id, objective_version) "
                "VALUES (:p, :i, :v, :r, :f, coalesce(CAST(:ov AS integer), (SELECT o.version "
                "FROM projects pr JOIN research_objectives o ON o.id = pr.active_objective_id "
                "WHERE pr.id = :p))) "
                "ON CONFLICT DO NOTHING RETURNING item_id"
            ),
            {
                "p": project_id,
                "i": item_id,
                "v": discovered_via.value,
                "r": run_id,
                "f": from_item_id,
                "ov": objective_version,
            },
        )
        return added is not None

    async def move_versions(
        self,
        session: AsyncSession,
        to_paper: uuid.UUID,
        *,
        from_paper: uuid.UUID | None = None,
        manifestation_ids: list[uuid.UUID] | None = None,
    ) -> None:
        """HAS_VERSION moves (merge or split): the old edges get deletion markers."""
        if (from_paper is None) == (manifestation_ids is None):
            raise ValueError("give from_paper or manifestation_ids")
        async with _settings(session, deletion_reason=TombstoneReason.MERGE_SPLIT.value):
            if from_paper is not None:
                await session.execute(
                    sa.text("UPDATE paper_manifestations SET paper_id = :t WHERE paper_id = :f"),
                    {"t": to_paper, "f": from_paper},
                )
            else:
                await session.execute(
                    sa.text("UPDATE paper_manifestations SET paper_id = :t WHERE id = ANY(:ids)"),
                    {"t": to_paper, "ids": manifestation_ids},
                )

    async def merge_project_items(
        self, session: AsyncSession, survivor: uuid.UUID, merged: uuid.UUID
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """Membership moves to the survivor; where the survivor is already in that project,
        the merged work's row is returned (kept in the merge event, restored by a split)."""
        async with _settings(session, deletion_reason=TombstoneReason.MERGE_SPLIT.value):
            dropped = [
                dict(r.row)
                for r in await session.execute(
                    sa.text(
                        "DELETE FROM project_items pi WHERE pi.item_id = :m AND EXISTS ("
                        "SELECT 1 FROM project_items s WHERE s.project_id = pi.project_id "
                        "AND s.item_id = :s) RETURNING to_jsonb(pi.*) AS row"
                    ),
                    {"s": survivor, "m": merged},
                )
            ]
            moved = [
                str(r.project_id)
                for r in await session.execute(
                    sa.text(
                        "UPDATE project_items SET item_id = :s WHERE item_id = :m "
                        "RETURNING project_id"
                    ),
                    {"s": survivor, "m": merged},
                )
            ]
        return moved, dropped

    async def split_project_items(
        self,
        session: AsyncSession,
        survivor: uuid.UUID,
        merged: uuid.UUID,
        moved_projects: list[uuid.UUID],
        dropped_rows: list[dict[str, Any]],
    ) -> None:
        """Undo ``merge_project_items`` exactly."""
        async with _settings(session, deletion_reason=TombstoneReason.MERGE_SPLIT.value):
            for project_id in moved_projects:
                await session.execute(
                    sa.text(
                        "UPDATE project_items SET item_id = :m "
                        "WHERE project_id = :p AND item_id = :s"
                    ),
                    {"m": merged, "s": survivor, "p": project_id},
                )
            for row in dropped_rows:
                await session.execute(
                    sa.text(
                        "INSERT INTO project_items SELECT * FROM "
                        "jsonb_populate_record(NULL::project_items, CAST(:r AS jsonb)) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {"r": json.dumps(row, default=str)},
                )

    # Reads -------------------------------------------------------------------------------

    async def get(self, session: AsyncSession, uid: uuid.UUID) -> StoredRelation:
        for table in sorted(registry.RESEARCH_TABLES):
            spec = next(s for s in registry.AVAILABLE if s.source_table == table)
            uid_col = _uid_column(table)
            type_expr = (
                f"upper({spec.type_discriminator})" if spec.type_discriminator else f"'{spec.type}'"
            )
            row = (
                (
                    await session.execute(
                        sa.text(
                            f"SELECT {uid_col} AS uid, {type_expr} AS type, "  # noqa: S608
                            f"{spec.from_column} AS from_uid, {spec.to_column} AS to_uid, "
                            "assertion, status, scope_project_id, confidence, evidence, provenance "
                            f"FROM {table} WHERE {uid_col} = :u"
                        ),
                        {"u": uid},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is not None:
                return StoredRelation(
                    table=table,
                    uid=row["uid"],
                    type=row["type"],
                    from_uid=row["from_uid"],
                    to_uid=row["to_uid"],
                    assertion=Assertion(row["assertion"]),
                    status=RelationStatus(row["status"]),
                    scope_project_id=row["scope_project_id"],
                    confidence=None if row["confidence"] is None else float(row["confidence"]),
                    evidence=row["evidence"],
                    provenance=row["provenance"],
                )
        raise NotFound("relationship not found")

    # Internals ---------------------------------------------------------------------------

    async def _visible(
        self, session: AsyncSession, ctx: WriteContext, uid: uuid.UUID
    ) -> StoredRelation:
        rel = await self.get(session, uid)
        if rel.scope_project_id not in (None, ctx.project_id):
            raise NotFound("relationship not found")  # another project's: not revealed
        return rel

    async def _check_endpoints(
        self,
        session: AsyncSession,
        spec: RelationSpec,
        rel: NewRelation,
        scope: uuid.UUID | None,
    ) -> tuple[str, str]:
        if spec.scope_policy is ScopePolicy.GLOBAL_ONLY and scope is not None:
            raise RelationRejected(f"{rel.type} is global-only knowledge")
        if spec.scope_policy is ScopePolicy.PROJECT_ONLY and scope is None:
            raise RelationRejected(f"{rel.type} exists only within a project")
        nodes = {
            r.uid: r
            for r in await session.execute(
                sa.text("SELECT uid, kind, scope_project_id FROM graph_nodes WHERE uid = ANY(:u)"),
                {"u": [rel.from_uid, rel.to_uid]},
            )
        }
        a, b = nodes.get(rel.from_uid), nodes.get(rel.to_uid)
        if a is None or b is None:
            raise RelationRejected(f"{rel.type}: both endpoints must be existing graph nodes")
        if spec.projected and not registry.allowed(rel.type, a.kind, b.kind):
            raise RelationRejected(f"{rel.type} from {a.kind} to {b.kind} is not allowed")
        sa_, sb = a.scope_project_id, b.scope_project_id
        if sa_ is not None and sb is not None and sa_ != sb:
            raise RelationRejected(f"{rel.type} cannot connect nodes of different projects")
        node_scope = sa_ or sb
        if node_scope is not None and scope != node_scope:
            raise RelationRejected(
                f"{rel.type} touches a project's node and must be written in that project"
            )
        return str(a.kind), str(b.kind)

    def _check_assertion(
        self, ctx: WriteContext, rel: NewRelation, scope: uuid.UUID | None
    ) -> None:
        assertion = rel.assertion
        if assertion in (Assertion.STRUCTURAL, Assertion.REJECTED):
            raise RelationRejected(f"a new relationship cannot be {assertion.value}")
        if scope is None and assertion not in GLOBAL_ASSERTIONS:
            raise RelationRejected(
                f"a global relationship cannot be {assertion.value}; "
                "write it in the project it belongs to"
            )
        if (assertion in USER_ASSERTIONS) != ctx.is_user:
            raise RelationRejected("user assertions are written by users, and only by them")
        if assertion in _NO_CONFIDENCE and rel.confidence is not None:
            raise RelationRejected(f"{assertion.value} relationships carry no confidence")

    async def _check_evidence(self, session: AsyncSession, rel: NewRelation) -> None:
        ev, prov, a = rel.evidence, rel.provenance, rel.assertion
        if a is Assertion.SOURCE_METADATA:
            if not ev.source_record_ids:
                raise RelationRejected("source_metadata needs the source record that reported it")
            found = await session.scalar(
                sa.text("SELECT count(*) FROM source_records WHERE id = ANY(:ids)"),
                {"ids": ev.source_record_ids},
            )
            if found != len(set(ev.source_record_ids)):
                raise RelationRejected("unknown source record in evidence")
        elif a in (Assertion.AUTHOR_REPORTED, Assertion.EXTRACTED):
            rows = (
                (
                    await session.execute(
                        sa.text("SELECT verification FROM evidence_spans WHERE id = ANY(:ids)"),
                        {"ids": ev.span_ids},
                    )
                )
                .scalars()
                .all()
            )
            if len(rows) != len(set(ev.span_ids)):
                raise RelationRejected("unknown evidence span")
            if not any(v in ("exact", "fuzzy") for v in rows):
                raise RelationRejected(f"{a.value} needs at least one verified evidence span")
        elif a is Assertion.COMPUTED:
            if not (ev.signal_ids or ev.computation):
                raise RelationRejected("computed needs a signal or computation reference")
        elif a is Assertion.INFERRED:
            if rel.confidence is None or not (ev.span_ids or ev.signal_ids):
                raise RelationRejected("inferred needs a confidence and supporting evidence")
            if not (prov.task and prov.model):
                raise RelationRejected("inferred needs the producing task and model")
        elif a is Assertion.HYPOTHESIZED:
            if not (ev.derived_from or ev.span_ids) or not (prov.task and prov.model):
                raise RelationRejected(
                    "hypothesized needs its source and the producing task and model"
                )

    async def _find(self, session: AsyncSession, row: _Row) -> Mapping[str, Any] | None:
        where = " AND ".join(f"{c} IS NOT DISTINCT FROM :k_{c}" for c in row.key)
        result = await session.execute(
            sa.text(
                f"SELECT {row.uid_column} AS uid, * FROM {row.table} "  # noqa: S608
                f"WHERE {where} FOR UPDATE"
            ),
            {f"k_{c}": v for c, v in row.key.items()},
        )
        found = result.mappings().one_or_none()
        return dict(found) if found is not None else None

    async def _suppressed(
        self, session: AsyncSession, rel: NewRelation, scope: uuid.UUID | None, fp: str
    ) -> bool:
        exact = fingerprint(rel.type, rel.from_uid, rel.to_uid)
        text_only = (
            fingerprint(rel.type, rel.from_uid, None, rel.fingerprint_text)
            if rel.fingerprint_text
            else None
        )
        hit = await session.scalar(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM relation_suppressions WHERE type = :t "
                "AND from_uid = :a AND scope_project_id IS NOT DISTINCT FROM :s AND ("
                "(to_uid = :b AND fingerprint IN (:exact, :fp)) "
                "OR (to_uid IS NULL AND fingerprint = :text_only)))"
            ),
            {
                "t": rel.type,
                "a": rel.from_uid,
                "b": rel.to_uid,
                "s": scope,
                "exact": exact,
                "fp": fp,
                "text_only": text_only,
            },
        )
        return bool(hit)

    async def _add_suppression(
        self, session: AsyncSession, rel: StoredRelation, ctx: WriteContext, reason: str
    ) -> None:
        scope = ctx.project_id if rel.scope_project_id is None else rel.scope_project_id
        created_by = uuid.UUID(ctx.actor.id) if ctx.is_user else None
        prints = [(rel.to_uid, fingerprint(rel.type, rel.from_uid, rel.to_uid))]
        if rel.provenance.get("fingerprint"):
            prints.append((rel.to_uid, str(rel.provenance["fingerprint"])))
        for to_uid, fp in prints:
            await session.execute(
                sa.text(
                    "INSERT INTO relation_suppressions (id, type, from_uid, to_uid, fingerprint, "
                    "scope_project_id, reason, created_by) VALUES (:id, :t, :a, :b, :fp, :s, :r, "
                    ":u) ON CONFLICT DO NOTHING"
                ),
                {
                    "id": uuid7(),
                    "t": rel.type,
                    "a": rel.from_uid,
                    "b": to_uid,
                    "fp": fp,
                    "s": scope,
                    "r": reason,
                    "u": created_by,
                },
            )

    async def _decide(
        self,
        session: AsyncSession,
        ctx: WriteContext,
        rel: StoredRelation,
        decision: RelationDecisionKind,
        reason: str | None,
    ) -> None:
        await session.execute(
            sa.text(
                "INSERT INTO relation_decisions (id, scope_project_id, relation_table, "
                "relation_uid, decision, reason, decided_by) VALUES (:id, :p, :t, :u, :d, :r, :by) "
                "ON CONFLICT (scope_project_id, relation_uid) DO UPDATE SET "
                "decision = EXCLUDED.decision, reason = EXCLUDED.reason, "
                "decided_by = EXCLUDED.decided_by, decided_at = now()"
            ),
            {
                "id": uuid7(),
                "p": ctx.project_id,
                "t": rel.table,
                "u": rel.uid,
                "d": decision.value,
                "r": reason,
                "by": uuid.UUID(ctx.actor.id),
            },
        )

    async def _apply(
        self,
        session: AsyncSession,
        ctx: WriteContext,
        table: str,
        uid_column: str,
        uid: uuid.UUID,
        updates: dict[str, Any],
        reason: AssertionChangeReason | None,
    ) -> None:
        sets, params = [], {"uid": uid}
        for column, value in updates.items():
            placeholder, params[column] = _param(column, value)
            sets.append(f"{column} = {placeholder}")
        async with _settings(
            session,
            actor=str(ctx.actor),
            actor_scope=str(ctx.project_id) if ctx.project_id else "",
            change_reason=reason.value if reason else "",
        ):
            await session.execute(
                sa.text(
                    f"UPDATE {table} SET {', '.join(sets)} "  # noqa: S608
                    f"WHERE {uid_column} = :uid"
                ),
                params,
            )

    def _suppress(self, spec: RelationSpec, uid: uuid.UUID | None, why: str) -> WriteResult:
        log.info("relations.suppressed", type=spec.type, uid=str(uid) if uid else None, why=why)
        return WriteResult(uid, Outcome.SUPPRESSED, spec.source_table)


def _uid_column(table: str) -> str:
    return "relation_uid" if table in ("citations", "paper_authors") else "id"


def _same(stored: Any, new: Any) -> bool:
    if isinstance(new, StrEnum):
        new = new.value
    if stored is None or new is None:
        return stored is None and new is None
    if isinstance(new, float) or isinstance(stored, float):
        return abs(float(stored) - float(new)) < 1e-9
    return bool(stored == new)


relation_writer = RelationWriter()
