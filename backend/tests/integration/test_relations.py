"""Relationship infrastructure (task 6a): registry, RelationWriter, endpoint and scope rules,
evidence by assertion, natural keys, sticky rejection, overlays, deletion markers, audits.

Database rules are tested through RelationWriter *and* direct SQL that bypasses it.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from psycopg import errors
from psycopg.types.json import Jsonb
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.core.errors import NotFound
from researchpilot.core.ids import uuid7
from researchpilot.core.settings import BACKEND_ROOT
from researchpilot.domain.enums import Assertion
from researchpilot.relations import audit, ids, registry, tombstones
from researchpilot.relations.writer import (
    Computation,
    Evidence,
    NewRelation,
    Outcome,
    Provenance,
    RelationRejected,
    WriteContext,
    relation_writer,
)
from tests.integration.conftest import API, create_project

pytestmark = pytest.mark.integration

SYSTEM = Provenance(service="test-suite", service_version="1")
LLM = Provenance(service="relevance-judge", task="relevance", model="test-model")


# --- world builder (direct SQL, autocommit) ----------------------------------------------


@dataclass
class World:
    conn: psycopg.Connection

    def paper(self, title: str = "A paper") -> uuid.UUID:
        pid = uuid7()
        self.conn.execute("INSERT INTO research_items (id, item_type) VALUES (%s, 'paper')", (pid,))
        self.conn.execute(
            "INSERT INTO papers (id, title, normalized_title) VALUES (%s, %s, %s)",
            (pid, title, title.lower()),
        )
        return pid

    def manifestation(self, paper: uuid.UUID) -> uuid.UUID:
        mid = uuid7()
        self.conn.execute(
            "INSERT INTO paper_manifestations (id, paper_id, kind, server_or_venue, "
            "primary_identifier_scheme, primary_identifier_value, peer_review_label) "
            "VALUES (%s, %s, 'preprint', 'arXiv', 'arxiv', %s, 'preprint_not_peer_reviewed')",
            (mid, paper, f"2611.{uuid.uuid4().int % 99999:05d}"),
        )
        return mid

    def author(self) -> uuid.UUID:
        aid = uuid7()
        self.conn.execute(
            "INSERT INTO authors (id, display_name, normalized_name) VALUES (%s, 'A. Author', "
            "'a author')",
            (aid,),
        )
        return aid

    def group(self) -> uuid.UUID:
        gid = uuid7()
        self.conn.execute(
            "INSERT INTO research_groups (id, display_name, source) VALUES (%s, 'Lab', 'test')",
            (gid,),
        )
        return gid

    def entity(self, type_: str) -> uuid.UUID:
        eid = uuid7()
        self.conn.execute(
            "INSERT INTO research_items (id, item_type) VALUES (%s, %s)", (eid, type_)
        )
        self.conn.execute(
            "INSERT INTO entities (id, type, canonical_name) VALUES (%s, %s, %s)",
            (eid, type_, f"{type_}-{eid}"),
        )
        return eid

    def span(self, paper: uuid.UUID, verification: str = "exact") -> uuid.UUID:
        sid = uuid7()
        self.conn.execute(
            "INSERT INTO evidence_spans (id, paper_id, location_kind, quote, verification, "
            "created_by) VALUES (%s, %s, 'abstract', 'we propose', %s, 'test')",
            (sid, paper, verification),
        )
        return sid

    def source_record(self) -> uuid.UUID:
        rid = uuid7()
        self.conn.execute(
            "INSERT INTO source_records (id, source, source_entity_id, endpoint, payload, "
            "payload_sha256, fetched_at) VALUES (%s, 'semantic_scholar', %s, 'paper', '{}', "
            "%s, now())",
            (rid, str(rid), hashlib.sha256(rid.bytes).hexdigest()),
        )
        return rid

    def kind(self, uid: uuid.UUID) -> Any:
        row = self.conn.execute(
            "SELECT kind, scope_project_id FROM graph_nodes WHERE uid = %s", (uid,)
        ).fetchone()
        return row

    def tombstone(self, uid: uuid.UUID) -> Any:
        return self.conn.execute(
            "SELECT kind, reason FROM entity_tombstones WHERE uid = %s", (uid,)
        ).fetchone()


@pytest.fixture
def world(migrated_db: str) -> Iterator[World]:
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        yield World(conn)


@pytest.fixture
def sessions(app: FastAPI) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = app.state.sessions
    return factory


@pytest.fixture
async def session(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with sessions() as s, s.begin():
        yield s


async def write(
    sessions: async_sessionmaker[AsyncSession], ctx: WriteContext, rel: NewRelation
) -> Any:
    async with sessions() as s, s.begin():
        return await relation_writer.write(s, ctx, rel)


async def project_with_topics(client: httpx.AsyncClient) -> tuple[uuid.UUID, list[uuid.UUID]]:
    project_id = await create_project(client)
    resp = await client.post(
        f"{API}/projects/{project_id}/objective",
        json={
            "core_question": "Which GNNs work best?",
            "sub_questions": [{"text": "Which benchmarks?"}, {"text": "Which datasets?"}],
        },
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(project_id), [uuid.UUID(s["id"]) for s in resp.json()["sub_questions"]]


def local_user(conn: psycopg.Connection) -> uuid.UUID:
    row = conn.execute("SELECT id FROM users WHERE auth_provider = 'local_none'").fetchone()
    assert row is not None
    return uuid.UUID(str(row[0]))


def cites(a: uuid.UUID, b: uuid.UUID, record: uuid.UUID) -> NewRelation:
    return NewRelation(
        type="CITES",
        from_uid=a,
        to_uid=b,
        assertion=Assertion.SOURCE_METADATA,
        evidence=Evidence(source_record_ids=[record]),
        provenance=SYSTEM,
        properties={"sources": ["semantic_scholar"]},
    )


def related(a: uuid.UUID, b: uuid.UUID, span: uuid.UUID, **extra: Any) -> NewRelation:
    return NewRelation(
        type="RELATED_TO",
        from_uid=a,
        to_uid=b,
        assertion=Assertion.INFERRED,
        confidence=0.7,
        evidence=Evidence(span_ids=[span]),
        provenance=LLM,
        **extra,
    )


def sql_research(
    conn: psycopg.Connection,
    type_: str,
    a: uuid.UUID,
    a_kind: str,
    b: uuid.UUID,
    b_kind: str,
    scope: uuid.UUID | None,
    assertion: str = "computed",
    evidence: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    confidence: float | None = None,
) -> uuid.UUID:
    rid = uuid7()
    conn.execute(
        "INSERT INTO research_relations (id, type, from_uid, from_kind, to_uid, to_kind, "
        "assertion, confidence, evidence, provenance, scope_project_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            rid,
            type_,
            a,
            a_kind,
            b,
            b_kind,
            assertion,
            confidence,
            Jsonb(
                evidence
                if evidence is not None
                else {"computation": {"method": "cocitation", "version": "1"}}
            ),
            Jsonb(provenance or {"service": "sql"}),
            scope,
        ),
    )
    return rid


# --- registry: one source per type -------------------------------------------------------


async def test_every_type_has_exactly_one_source_and_matches_code(
    session: AsyncSession, world: World
) -> None:
    rows = world.conn.execute(
        "SELECT type, source_table, class, scope_policy FROM relation_registry ORDER BY type"
    ).fetchall()
    assert {r[0] for r in rows} == {s.type for s in registry.AVAILABLE}
    assert len(rows) == len({r[0] for r in rows})  # PK: one row per type
    expected = {
        "CITES": "citations",
        "AUTHORED_BY": "paper_authors",
        "AFFILIATED_WITH": "author_affiliations",
        "INTRODUCES": "entity_links",
        "USES_METHOD": "entity_links",
        "EVALUATES_ON": "entity_links",
        "EXTENDS": "research_relations",
        "CONTRADICTS": "research_relations",
        "RELATED_TO": "research_relations",
        "ADDRESSES": "research_relations",
        "DERIVED_FROM": "research_relations",
        "VALIDATED_BY": "research_relations",
        "HAS_VERSION": "paper_manifestations",
        "IN_PROJECT": "project_items",
        "PART_OF": "structural_relations",
    }
    assert {r[0]: r[1] for r in rows} == expected
    # Later sources are known to the code registry but not registered yet.
    assert {s.type for s in registry.SPECS if not s.available} == {
        "REPORTS_LIMITATION",
        "IMPLEMENTED_BY",
        "RESULT_FOR",
    }
    rules = {
        tuple(r)
        for r in world.conn.execute(
            "SELECT type, from_kind, to_kind FROM relation_endpoint_rules"
        ).fetchall()
    }
    assert rules == set(registry.ENDPOINT_RULES)
    assert await audit.check_enforcement(session) == []


async def test_enforcement_check_fails_for_a_registered_type_without_triggers(
    session: AsyncSession,
) -> None:
    await session.execute(
        sa.text(
            "INSERT INTO relation_registry (type, class, source_table, from_column, to_column, "
            "scope_column, scope_policy, projected, required_evidence_policy, introduced_in) "
            "VALUES ('DUMMY', 'research', 'evidence_spans', 'paper_id', 'manifestation_id', "
            "NULL, 'project_or_global', true, 'by_assertion', 'R1')"
        )
    )
    problems = await audit.check_enforcement(session)
    assert any("DUMMY" in p and "lacks trigger rp_relation_10_check" in p for p in problems)
    assert any("DUMMY" in p and "must be global_only" in p for p in problems)
    assert any("registry mismatch" in p for p in problems)
    await session.rollback()


def test_type_checks_on_the_shared_tables(world: World) -> None:
    a, b = world.paper(), world.paper()
    with pytest.raises(errors.CheckViolation):
        sql_research(world.conn, "CITES", a, "Paper", b, "Paper", None)
    with pytest.raises(errors.CheckViolation):
        world.conn.execute(
            "INSERT INTO structural_relations (id, type, child_uid, child_kind, parent_uid, "
            "parent_kind) VALUES (%s, 'RELATED_TO', %s, 'Paper', %s, 'Paper')",
            (uuid7(), a, b),
        )


async def test_no_hidden_second_sources(session: AsyncSession) -> None:
    assert await audit.undeclared_references(session) == []
    await session.execute(
        sa.text(
            "CREATE TABLE rogue_links (a uuid REFERENCES papers(id), b uuid REFERENCES authors(id))"
        )
    )
    problems = await audit.undeclared_references(session)
    assert sorted(problems) == [
        "rogue_links.a -> papers is neither a relationship source nor declared",
        "rogue_links.b -> authors is neither a relationship source nor declared",
    ]
    await session.rollback()


# --- identity --------------------------------------------------------------------------------


async def test_deterministic_edge_ids_match_python_and_sql(
    sessions: async_sessionmaker[AsyncSession], world: World
) -> None:
    migration = BACKEND_ROOT / "alembic" / "rp_sql" / "relations_0009.py"
    spec = importlib.util.spec_from_file_location("rel0009", migration)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert str(ids.RELATION_NAMESPACE) == module.RELATION_NAMESPACE

    a, b, rec = world.paper(), world.paper(), world.source_record()
    result = await write(sessions, WriteContext.system("s2-sync"), cites(a, b, rec))
    assert result.outcome is Outcome.CREATED
    assert result.uid == ids.relation_uid("CITES", "citations", a, b)
    sql_uid = world.conn.execute(
        "SELECT rp_relation_uid('CITES', 'citations', %s, %s, '')", (a, b)
    ).fetchone()
    assert sql_uid is not None and sql_uid[0] == result.uid

    m = world.manifestation(a)
    stored = world.conn.execute(
        "SELECT relation_uid FROM paper_manifestations WHERE id = %s", (m,)
    ).fetchone()
    assert stored == (ids.relation_uid("HAS_VERSION", "paper_manifestations", a, m),)
    # A forged identity is refused.
    with pytest.raises(errors.CheckViolation, match="deterministic"):
        world.conn.execute(
            "INSERT INTO citations (citing_id, cited_id, relation_uid, assertion, evidence) "
            "VALUES (%s, %s, %s, 'source_metadata', %s)",
            (b, a, uuid.uuid4(), Jsonb({"source_record_ids": [str(rec)]})),
        )


# --- endpoints ---------------------------------------------------------------------------


async def test_allowed_and_forbidden_endpoint_combinations(
    sessions: async_sessionmaker[AsyncSession], world: World
) -> None:
    ctx = WriteContext.system("extractor")
    paper, other, author = world.paper(), world.paper(), world.author()
    method, concept, term = world.entity("method"), world.entity("concept"), world.entity("term")
    assert world.kind(method)[0] == "Method" and world.kind(concept)[0] == "Topic"
    assert world.kind(term) is None  # glossary terms are not nodes
    span = world.span(paper)
    rec = world.source_record()

    authored = NewRelation(
        type="AUTHORED_BY",
        from_uid=paper,
        to_uid=author,
        assertion=Assertion.SOURCE_METADATA,
        evidence=Evidence(source_record_ids=[rec]),
        provenance=SYSTEM,
        properties={"position": 1, "raw_name": "A. Author"},
    )
    assert (await write(sessions, ctx, authored)).outcome is Outcome.CREATED
    introduces = NewRelation(
        type="INTRODUCES",
        from_uid=paper,
        to_uid=method,
        assertion=Assertion.EXTRACTED,
        evidence=Evidence(span_ids=[span]),
        provenance=SYSTEM,
    )
    assert (await write(sessions, ctx, introduces)).outcome is Outcome.CREATED
    assert (await write(sessions, ctx, related(paper, concept, span))).outcome is Outcome.CREATED

    bad = [
        authored.model_copy(update={"to_uid": other}),  # Paper -> Paper
        introduces.model_copy(update={"to_uid": concept}),  # Paper -> Topic
        introduces.model_copy(update={"to_uid": term}),  # not a node
        authored.model_copy(update={"to_uid": uuid.uuid4()}),  # missing node
    ]
    for rel in bad:
        with pytest.raises(RelationRejected):
            await write(sessions, ctx, rel)
    # The database refuses the same combinations without the writer.
    with pytest.raises(errors.CheckViolation, match="not an allowed combination"):
        sql_research(world.conn, "EXTENDS", paper, "Paper", method, "Method", None)
    with pytest.raises(errors.ForeignKeyViolation):
        sql_research(world.conn, "EXTENDS", paper, "Paper", uuid.uuid4(), "Paper", None)
    with pytest.raises(errors.ForeignKeyViolation):  # wrong kind for an existing node
        sql_research(world.conn, "EXTENDS", paper, "Paper", other, "Method", None)
    with pytest.raises((errors.ForeignKeyViolation, errors.CheckViolation)):
        world.conn.execute(
            "INSERT INTO entity_links (id, subject_uid, subject_kind, entity_id, role, "
            "assertion, evidence) VALUES (%s, %s, 'Paper', %s, 'introduces', 'extracted', %s)",
            (uuid7(), paper, term, Jsonb({"span_ids": [str(span)]})),
        )


# --- scope -------------------------------------------------------------------------------


async def test_cross_project_and_scope_rules(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession], world: World
) -> None:
    p, (tp, _) = await project_with_topics(client)
    q, (tq, _) = await project_with_topics(client)
    a, b = world.paper(), world.paper()
    span = world.span(a)

    # Writer: endpoints of two projects, wrong scope, global touching a project node.
    for ctx, rel in [
        (WriteContext.system("judge", p), related(tp, tq, span)),
        (WriteContext.system("judge", q), related(a, tp, span)),
        (WriteContext.system("judge", p), related(tq, a, span)),
        (WriteContext.system("judge"), related(a, tp, span)),
    ]:
        with pytest.raises(RelationRejected):
            await write(sessions, ctx, rel)
    # Database: the same, bypassing the writer.
    cases = [
        (tp, tq, p, "different projects"),
        (a, tp, q, "scope of its project-scoped endpoint"),
        (tq, a, p, "scope of its project-scoped endpoint"),
        (a, tp, None, "scope of its project-scoped endpoint"),
    ]
    for x, y, scope, message in cases:
        with pytest.raises(errors.CheckViolation, match=message):
            sql_research(world.conn, "RELATED_TO", x, world.kind(x)[0], y, world.kind(y)[0], scope)

    # Accepted: global node + P node with scope P; two global nodes globally or in P.
    ok = await write(sessions, WriteContext.system("judge", p), related(a, tp, span))
    assert ok.outcome is Outcome.CREATED
    assert (await write(sessions, WriteContext.system("judge"), related(a, b, span))).uid
    in_p = await write(sessions, WriteContext.system("judge", p), related(a, b, span))
    assert in_p.outcome is Outcome.CREATED  # a separate, project-scoped assertion

    rec = world.source_record()
    with pytest.raises(RelationRejected, match="global-only"):
        await write(sessions, WriteContext.system("s2", p), cites(a, b, rec))
    with pytest.raises(errors.CheckViolation):  # CHECK (scope_project_id IS NULL)
        world.conn.execute(
            "INSERT INTO citations (citing_id, cited_id, assertion, evidence, "
            "scope_project_id) VALUES (%s, %s, 'source_metadata', %s, %s)",
            (a, b, Jsonb({"source_record_ids": [str(rec)]}), p),
        )
    validated = NewRelation(
        type="VALIDATED_BY",
        from_uid=a,
        to_uid=b,
        assertion=Assertion.COMPUTED,
        evidence=Evidence(computation=Computation(method="m", version="1")),
        provenance=SYSTEM,
    )
    with pytest.raises(RelationRejected, match="within a project"):
        await write(sessions, WriteContext.system("x"), validated)

    # Global-scope rule: no project context, no user assertions.
    with pytest.raises(errors.CheckViolation, match="project context"):
        sql_research(
            world.conn,
            "RELATED_TO",
            a,
            "Paper",
            b,
            "Paper",
            None,
            provenance={"service": "x", "project_context": True},
        )
    with pytest.raises(errors.CheckViolation, match="cannot have assertion"):
        sql_research(
            world.conn,
            "RELATED_TO",
            b,
            "Paper",
            a,
            "Paper",
            None,
            assertion="user_asserted",
            provenance={"service": "x", "actor": "user:1", "at": "now"},
        )
    with pytest.raises(RelationRejected, match="global relationship cannot be user_asserted"):
        user = WriteContext(None, WriteContext.user(local_user(world.conn), p).actor)
        await write(
            sessions,
            user,
            NewRelation(
                type="RELATED_TO",
                from_uid=b,
                to_uid=a,
                assertion=Assertion.USER_ASSERTED,
                provenance=SYSTEM,
            ),
        )


async def test_has_version_cannot_touch_a_project_node(
    client: httpx.AsyncClient, world: World
) -> None:
    """R1-65 (p): crafted project-scoped graph node for a work; HAS_VERSION is refused."""
    paper = world.paper()
    project = await create_project(client)
    world.conn.execute("DELETE FROM graph_nodes WHERE uid = %s", (paper,))
    world.conn.execute(
        "INSERT INTO graph_nodes (uid, kind, scope_project_id) VALUES (%s, 'Paper', %s)",
        (paper, project),
    )
    with pytest.raises(errors.CheckViolation):
        world.manifestation(paper)
    world.conn.execute("DELETE FROM graph_nodes WHERE uid = %s", (paper,))
    world.conn.execute("INSERT INTO graph_nodes (uid, kind) VALUES (%s, 'Paper')", (paper,))


# --- assertion classes and evidence ------------------------------------------------------


async def test_structural_relationships_are_not_findings(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession], world: World
) -> None:
    p, (topic, _) = await project_with_topics(client)
    a = world.paper()
    with pytest.raises(errors.CheckViolation):
        sql_research(
            world.conn, "RELATED_TO", a, "Paper", topic, "Topic", p, assertion="structural"
        )
    rec = world.source_record()
    with pytest.raises(errors.CheckViolation, match="structural"):
        world.conn.execute(
            "INSERT INTO citations (citing_id, cited_id, assertion, evidence) "
            "VALUES (%s, %s, 'structural', %s)",
            (a, world.paper(), Jsonb({"source_record_ids": [str(rec)]})),
        )
    with pytest.raises(errors.CheckViolation):
        world.conn.execute(
            "UPDATE structural_relations SET assertion = 'inferred' WHERE child_uid = %s",
            (topic,),
        )
    columns = {
        r[0]
        for r in world.conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'structural_relations'"
        )
    }
    assert not {"evidence", "confidence", "provenance", "status"} & columns
    with pytest.raises(RelationRejected, match="structural"):
        await write(
            sessions,
            WriteContext.system("x", p),
            NewRelation(
                type="PART_OF",
                from_uid=topic,
                to_uid=p,
                assertion=Assertion.COMPUTED,
                provenance=SYSTEM,
            ),
        )
    # Shown as structural, never as a finding.
    objective = (await client.get(f"{API}/projects/{p}/objective")).json()["id"]
    view = (await client.get(f"{API}/projects/{p}/graph/nodes/{objective}/neighbors")).json()
    assert {(e["type"], e["assertion"]) for e in view["edges"]} == {("PART_OF", "structural")}


async def test_evidence_is_required_by_assertion(
    sessions: async_sessionmaker[AsyncSession], world: World
) -> None:
    a, b = world.paper(), world.paper()
    verified, unverified, rec = world.span(a), world.span(a, "unverified"), world.source_record()
    ctx = WriteContext.system("x")
    rejected: list[NewRelation] = [
        cites(a, b, rec).model_copy(update={"evidence": Evidence()}),
        cites(a, b, rec).model_copy(update={"confidence": 0.5}),
        cites(a, b, rec).model_copy(update={"evidence": Evidence(source_record_ids=[uuid7()])}),
        related(a, b, verified).model_copy(update={"confidence": None}),
        related(a, b, verified).model_copy(update={"provenance": SYSTEM}),
        related(a, b, verified).model_copy(update={"evidence": Evidence()}),
        NewRelation(
            type="EXTENDS",
            from_uid=a,
            to_uid=b,
            assertion=Assertion.EXTRACTED,
            evidence=Evidence(span_ids=[unverified]),
            provenance=SYSTEM,
        ),
        NewRelation(
            type="EXTENDS", from_uid=a, to_uid=b, assertion=Assertion.COMPUTED, provenance=SYSTEM
        ),
    ]
    for rel in rejected:
        with pytest.raises(RelationRejected):
            await write(sessions, ctx, rel)
    # The database enforces the same rules for direct SQL.
    cases: list[tuple[str, dict[str, Any], dict[str, Any], float | None, str]] = [
        ("extracted", {"span_ids": [str(unverified)]}, {"service": "x"}, None, "verified"),
        ("computed", {}, {"service": "x"}, None, "computation"),
        ("inferred", {"span_ids": [str(verified)]}, {"service": "x"}, 0.5, "task and model"),
        (
            "inferred",
            {"span_ids": [str(verified)]},
            {"task": "t", "model": "m"},
            None,
            "confidence",
        ),
        ("source_metadata", {"source_record_ids": [str(uuid7())]}, {}, None, "source record"),
    ]
    for assertion, evidence, provenance, confidence, message in cases:
        with pytest.raises(errors.CheckViolation, match=message):
            sql_research(
                world.conn,
                "EXTENDS",
                a,
                "Paper",
                b,
                "Paper",
                None,
                assertion=assertion,
                evidence=evidence,
                provenance=provenance,
                confidence=confidence,
            )
    ok = NewRelation(
        type="EXTENDS",
        from_uid=a,
        to_uid=b,
        assertion=Assertion.EXTRACTED,
        evidence=Evidence(span_ids=[verified, unverified]),
        provenance=SYSTEM,
    )
    assert (await write(sessions, ctx, ok)).outcome is Outcome.CREATED


# --- natural keys and duplicates --------------------------------------------------------


async def test_natural_keys_deduplicate_and_never_downgrade(
    sessions: async_sessionmaker[AsyncSession], world: World
) -> None:
    a, b, rec = world.paper(), world.paper(), world.source_record()
    ctx = WriteContext.system("s2")
    first = await write(sessions, ctx, cites(a, b, rec))
    again = await write(sessions, ctx, cites(a, b, rec))
    assert (first.outcome, again.outcome) == (Outcome.CREATED, Outcome.UNCHANGED)
    assert again.uid == first.uid
    count = world.conn.execute(
        "SELECT count(*) FROM citations WHERE citing_id = %s AND cited_id = %s", (a, b)
    ).fetchone()
    assert count == (1,)

    span = world.span(a)
    inferred = await write(sessions, ctx, related(a, b, span))
    extracted = related(a, b, span).model_copy(
        update={"assertion": Assertion.EXTRACTED, "confidence": None}
    )
    promoted = await write(sessions, ctx, extracted)
    assert (promoted.uid, promoted.outcome) == (inferred.uid, Outcome.UPDATED)
    log = world.conn.execute(
        "SELECT from_assertion, to_assertion, reason FROM relation_assertion_log "
        "WHERE relation_uid = %s",
        (inferred.uid,),
    ).fetchall()
    assert log == [("inferred", "extracted", "quote_verified")]
    # An inferred write never downgrades the extracted relationship.
    assert (await write(sessions, ctx, related(a, b, span))).outcome is Outcome.UNCHANGED
    # A different qualifier is a different relationship.
    other = await write(sessions, ctx, related(a, b, span, properties={"qualifier": "co_citation"}))
    assert other.uid != inferred.uid

    # Concurrent writers of the same new relationship produce one row.
    c, d = world.paper(), world.paper()
    results = await asyncio.gather(*[write(sessions, ctx, cites(c, d, rec)) for _ in range(4)])
    assert len({r.uid for r in results}) == 1
    assert sorted(r.outcome for r in results).count(Outcome.CREATED) == 1


# --- rejection -----------------------------------------------------------------------------


async def test_rejection_is_sticky_and_suppressed(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession], world: World
) -> None:
    p, (topic, _) = await project_with_topics(client)
    user = WriteContext.user(local_user(world.conn), p)
    judge = WriteContext.system("judge", p)
    a = world.paper()
    span = world.span(a)
    rel = related(a, topic, span, fingerprint_text="Only small datasets")
    uid = (await write(sessions, judge, rel)).uid
    assert uid is not None

    async with sessions() as s, s.begin():
        stored = await relation_writer.reject(s, user, uid, "wrong topic")
    assert stored.assertion is Assertion.REJECTED
    assert world.tombstone(uid) == ("RELATED_TO", "rejected")
    assert world.conn.execute(
        "SELECT to_assertion, reason, actor FROM relation_assertion_log WHERE relation_uid = %s",
        (uid,),
    ).fetchall() == [("rejected", "user_rejected", f"user:{local_user(world.conn)}")]

    # (a) the same automatic write, (b) a near-duplicate with different wording/qualifier.
    assert (await write(sessions, judge, rel)).outcome is Outcome.SUPPRESSED
    near = related(
        a,
        topic,
        span,
        fingerprint_text="only  SMALL datasets!",
        properties={"qualifier": "reworded"},
    )
    assert (await write(sessions, judge, near)).outcome is Outcome.SUPPRESSED
    assert world.conn.execute(
        "SELECT count(*) FROM research_relations WHERE from_uid = %s", (a,)
    ).fetchone() == (1,)
    # The database keeps it rejected against anything but a user in its project.
    with pytest.raises(errors.CheckViolation, match="only be changed by a user"):
        world.conn.execute(
            "UPDATE research_relations SET assertion = 'inferred' WHERE id = %s", (uid,)
        )
    with pytest.raises(errors.CheckViolation, match="rejected relationships are kept"):
        world.conn.execute("DELETE FROM research_relations WHERE id = %s", (uid,))
    # Only a user action brings it back.
    async with sessions() as s, s.begin():
        restored = await relation_writer.confirm(s, user, uid)
    assert restored.assertion is Assertion.USER_CONFIRMED
    assert world.tombstone(uid) is None  # eligible for the graph again


async def test_decisions_on_global_relationships_are_project_overlays(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession], world: World
) -> None:
    p = uuid.UUID(await create_project(client))
    q = uuid.UUID(await create_project(client))
    me = local_user(world.conn)
    a, b, c, rec = world.paper(), world.paper(), world.paper(), world.source_record()
    ab = (await write(sessions, WriteContext.system("s2"), cites(a, b, rec))).uid
    ac = (await write(sessions, WriteContext.system("s2"), cites(a, c, rec))).uid
    assert ab is not None and ac is not None

    async with sessions() as s, s.begin():
        await relation_writer.reject(s, WriteContext.user(me, p), ab, "not a real citation")
        await relation_writer.confirm(s, WriteContext.user(me, p), ac)
    row = world.conn.execute(
        "SELECT assertion, row_version FROM citations WHERE relation_uid = %s", (ab,)
    ).fetchone()
    assert row == ("source_metadata", 1)  # the global row is unchanged
    decisions = world.conn.execute(
        "SELECT relation_uid, decision FROM relation_decisions WHERE scope_project_id = %s",
        (p,),
    ).fetchall()
    assert set(decisions) == {(ab, "rejected"), (ac, "confirmed")}
    assert world.conn.execute(
        "SELECT count(*) FROM relation_suppressions WHERE scope_project_id = %s", (p,)
    ).fetchone() == (1,)

    def edges(view: dict[str, Any]) -> dict[str, str]:
        return {e["uid"]: e["assertion"] for e in view["edges"]}

    in_p = (await client.get(f"{API}/projects/{p}/graph/nodes/{a}/neighbors")).json()
    in_q = (await client.get(f"{API}/projects/{q}/graph/nodes/{a}/neighbors")).json()
    assert edges(in_p) == {str(ac): "user_confirmed"}
    assert edges(in_q) == {str(ab): "source_metadata", str(ac): "source_metadata"}

    # A user can never change the global row itself; system verification can.
    with pytest.raises(errors.CheckViolation, match="system verification"):
        world.conn.execute(
            "UPDATE citations SET assertion = 'rejected', provenance = provenance || "
            '\'{"rejected_by": "user:x", "rejection_reason": "no"}\' '
            "WHERE relation_uid = %s",
            (ab,),
        )
    async with sessions() as s, s.begin():
        await relation_writer.system_reject(s, ab, "quote-verifier", "not in reference list")
    assert world.conn.execute(
        "SELECT assertion FROM citations WHERE relation_uid = %s", (ab,)
    ).fetchone() == ("rejected",)
    assert world.tombstone(ab) == ("CITES", "rejected")
    # Another project's relationship is invisible to decisions.
    other_scoped = (
        await write(sessions, WriteContext.system("judge", q), related(b, c, world.span(b)))
    ).uid
    assert other_scoped is not None
    with pytest.raises(NotFound):
        async with sessions() as s, s.begin():
            await relation_writer.reject(s, WriteContext.user(me, p), other_scoped, "x")


async def test_writer_refuses_unknown_unavailable_and_misattributed_writes(
    sessions: async_sessionmaker[AsyncSession], world: World
) -> None:
    a, b = world.paper(), world.paper()
    with pytest.raises(ValueError, match="unknown relationship type"):
        NewRelation(
            type="LIKES", from_uid=a, to_uid=b, assertion=Assertion.COMPUTED, provenance=SYSTEM
        )
    with pytest.raises(ValueError, match="arrives in R2"):
        NewRelation(
            type="REPORTS_LIMITATION",
            from_uid=a,
            to_uid=b,
            assertion=Assertion.EXTRACTED,
            provenance=SYSTEM,
        )
    user_claim = NewRelation(
        type="EXTENDS", from_uid=a, to_uid=b, assertion=Assertion.USER_ASSERTED, provenance=SYSTEM
    )
    with pytest.raises(RelationRejected, match="global relationship cannot be user_asserted"):
        await write(sessions, WriteContext.system("x"), user_claim)
    with pytest.raises(RelationRejected, match="cannot be rejected"):
        await write(
            sessions,
            WriteContext.system("x"),
            user_claim.model_copy(update={"assertion": Assertion.REJECTED}),
        )
    with pytest.raises(RelationRejected, match="no properties"):
        await write(
            sessions,
            WriteContext.system("x"),
            cites(a, b, world.source_record()).model_copy(update={"properties": {"note": "x"}}),
        )


# --- deletion markers ------------------------------------------------------------------


def test_markers_hold_minimum_metadata_only(world: World) -> None:
    columns = {
        r[0]
        for r in world.conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'entity_tombstones'"
        )
    }
    assert columns == {
        "uid",
        "kind",
        "reason",
        "deleted_at",
        "graph_removed_at",
        "verified_absent_at",
        "attempts",
        "purge_after",
    }
    log_columns = {
        r[0]
        for r in world.conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'deletion_log'"
        )
    }
    assert log_columns == {
        "id",
        "subject_hash",
        "scope",
        "object_counts",
        "requested_at",
        "completed_at",
    }


async def test_project_deletion_writes_markers_and_removes_project_data(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    world: World,
    migrated_db: str,
) -> None:
    p, topics = await project_with_topics(client)
    objective = uuid.UUID((await client.get(f"{API}/projects/{p}/objective")).json()["id"])
    paper = world.paper()
    m = world.manifestation(paper)
    added = await client.post(f"{API}/projects/{p}/papers", json={"identifier": "arXiv:1706.03762"})
    assert added.status_code == 201
    item = uuid.UUID(added.json()["id"])
    other, rec = world.paper(), world.source_record()
    global_edge = (await write(sessions, WriteContext.system("s2"), cites(paper, other, rec))).uid
    span = world.span(paper)
    scoped = (
        await write(sessions, WriteContext.system("judge", p), related(paper, other, span))
    ).uid
    on_topic = (
        await write(sessions, WriteContext.system("judge", p), related(paper, topics[0], span))
    ).uid
    me = local_user(world.conn)
    async with sessions() as s, s.begin():
        await relation_writer.reject(s, WriteContext.user(me, p), on_topic, "off topic")
        await relation_writer.reject(s, WriteContext.user(me, p), global_edge, "no")
    part_of = [
        r[0]
        for r in world.conn.execute(
            "SELECT id FROM structural_relations WHERE scope_project_id = %s", (p,)
        )
    ]
    in_project = world.conn.execute(
        "SELECT relation_uid FROM project_items WHERE project_id = %s", (p,)
    ).fetchone()
    assert in_project is not None

    # Only the owner can delete; archiving stays the default.
    world.conn.execute("UPDATE project_members SET role = 'editor' WHERE project_id = %s", (p,))
    forbidden = await client.delete(f"{API}/projects/{p}", params={"permanent": "true"})
    assert forbidden.status_code == 403
    world.conn.execute("UPDATE project_members SET role = 'owner' WHERE project_id = %s", (p,))
    resp = await client.delete(f"{API}/projects/{p}", params={"permanent": "true"})
    assert resp.status_code == 204

    for table, column in [
        ("projects", "id"),
        ("research_objectives", "project_id"),
        ("research_relations", "scope_project_id"),
        ("relation_decisions", "scope_project_id"),
        ("relation_suppressions", "scope_project_id"),
        ("relation_assertion_log", "scope_project_id"),
        ("project_items", "project_id"),
        ("graph_nodes", "scope_project_id"),
        ("domain_events", "project_id"),
    ]:
        assert world.conn.execute(
            f"SELECT count(*) FROM {table} WHERE {column} = %s", (p,)
        ).fetchone() == (0,), table
    # Markers for every project-scoped node and edge, reason project_delete.
    expected = {
        p: "Project",
        objective: "Objective",
        topics[0]: "Topic",
        topics[1]: "Topic",
        **{uid: "PART_OF" for uid in part_of},
        in_project[0]: "IN_PROJECT",
        scoped: "RELATED_TO",
        on_topic: "RELATED_TO",
    }
    for uid, kind in expected.items():
        assert world.tombstone(uid) == (kind, "project_delete"), kind
    # Global knowledge stays, unchanged and without markers.
    assert world.conn.execute(
        "SELECT assertion FROM citations WHERE relation_uid = %s", (global_edge,)
    ).fetchone() == ("source_metadata",)
    for uid in (paper, other, m, item):
        assert world.kind(uid) is not None and world.tombstone(uid) is None
    # The audit keeps a hash and counts only.
    entry = world.conn.execute(
        "SELECT subject_hash, scope, object_counts FROM deletion_log ORDER BY requested_at DESC "
        "LIMIT 1"
    ).fetchone()
    assert entry is not None
    assert entry[1] == "project" and str(p) not in entry[0] and str(p) not in str(entry[2])
    assert entry[2]["graph_nodes"] == 4 and entry[2]["relationships"]["research_relations"] == 2

    # Purge: verified-absent markers at once, the rest at the 30-day cap.
    now = datetime.now(UTC)
    async with sessions() as s, s.begin():
        await tombstones.mark_absent(s, [p], now)
        report = await tombstones.purge(s, now, graph_enabled=False)
    assert report.purged >= 1 and world.tombstone(p) is None
    assert world.tombstone(objective) is not None
    async with sessions() as s, s.begin():
        await tombstones.purge(s, now + timedelta(days=31), graph_enabled=False)
    assert world.tombstone(objective) is None and world.tombstone(scoped) is None


async def test_moves_and_deletions_of_edges_write_markers(
    sessions: async_sessionmaker[AsyncSession], world: World
) -> None:
    a, b = world.paper(), world.paper()
    m = world.manifestation(b)
    old_edge = ids.relation_uid("HAS_VERSION", "paper_manifestations", b, m)
    async with sessions() as s, s.begin():
        await relation_writer.move_versions(s, a, manifestation_ids=[m])
    assert world.tombstone(old_edge) == ("HAS_VERSION", "merge_split")
    new_edge = world.conn.execute(
        "SELECT relation_uid FROM paper_manifestations WHERE id = %s", (m,)
    ).fetchone()
    assert new_edge == (ids.relation_uid("HAS_VERSION", "paper_manifestations", a, m),)
    # Moving back restores the old identity and clears its marker.
    async with sessions() as s, s.begin():
        await relation_writer.move_versions(s, b, manifestation_ids=[m])
    assert world.tombstone(old_edge) is None

    rec = world.source_record()
    edge = (await write(sessions, WriteContext.system("s2"), cites(a, b, rec))).uid
    assert edge is not None
    world.conn.execute("DELETE FROM papers WHERE id = %s", (b,))
    assert world.tombstone(edge) == ("CITES", "user_delete")
    assert world.tombstone(b) == ("Paper", "user_delete")
    assert world.tombstone(m) == ("PaperVersion", "user_delete")


# --- graph-node registration and orphans ------------------------------------------------


async def test_registration_and_orphan_detection(
    client: httpx.AsyncClient, session: AsyncSession, world: World
) -> None:
    await project_with_topics(client)
    author, method, term = world.author(), world.entity("dataset"), world.entity("term")
    assert world.kind(author) == ("Author", None)
    assert world.kind(method) == ("Dataset", None)
    assert world.kind(term) is None
    assert await audit.find_orphans(session) == []

    stray = uuid.uuid4()
    await session.execute(
        sa.text("INSERT INTO graph_nodes (uid, kind) VALUES (:u, 'Author')"), {"u": stray}
    )
    await session.execute(sa.text("DELETE FROM graph_nodes WHERE uid = :u"), {"u": author})
    found = {(o.uid, o.problem) for o in await audit.find_orphans(session)}
    assert found == {(stray, "no_source_row"), (author, "missing_node")}
    await session.rollback()
    # Kind and scope of a registered node are fixed.
    with pytest.raises(errors.CheckViolation):
        world.conn.execute("UPDATE entities SET type = 'metric' WHERE id = %s", (method,))


async def test_worker_purges_markers_daily(
    settings: Any, sources_transport: Any, world: World
) -> None:
    from researchpilot.core.clock import FixedClock
    from researchpilot.worker.main import TOMBSTONE_PURGE_JOB, build_worker

    day = datetime(2026, 12, 20, 10, tzinfo=UTC)
    uid = uuid.uuid4()
    world.conn.execute(
        "INSERT INTO entity_tombstones (uid, kind, reason, purge_after) "
        "VALUES (%s, 'Paper', 'user_delete', %s)",
        (uid, day - timedelta(days=1)),
    )
    worker, close = await build_worker(
        settings,
        source_transport=sources_transport,
        source_rate_limits=False,
        clock=FixedClock(day),
    )
    try:
        assert await worker.schedule_maintenance()
        assert not await worker.schedule_maintenance()  # once per UTC day
        while await worker.tick():
            pass
    finally:
        await close()
    assert world.tombstone(uid) is None
    assert world.conn.execute(
        "SELECT status FROM jobs WHERE kind = %s AND dedupe_key LIKE %s",
        (TOMBSTONE_PURGE_JOB, "%2026-12-20"),
    ).fetchone() == ("succeeded",)
