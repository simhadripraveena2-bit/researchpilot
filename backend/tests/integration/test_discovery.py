"""Discovery workflow W1, end to end with recorded source responses (no network).

The recorded run (scripts/record_discovery_fixtures.py, tests/fixtures/discovery.py): arXiv
and Crossref answered every query; Semantic Scholar answered Q2 and was rate limited (429) on
Q1 and Q3, so Q4 was not sent; OpenAlex's daily budget was exhausted (one 429).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg
import pytest
from pydantic import SecretStr

from researchpilot.core.ids import uuid7
from researchpilot.core.settings import Settings
from researchpilot.db.session import make_engine, make_sessionmaker, session_scope
from researchpilot.domain.enums import ReleaseType, SourceName
from researchpilot.integrations.base import SourceRecordStore
from researchpilot.relations.ids import relation_uid
from researchpilot.services.discovery import relate, resolve
from researchpilot.services.discovery import summary as summary_mod
from researchpilot.worker.main import build_worker
from tests.fixtures.discovery import OBJECTIVE, RUN_CONFIG
from tests.fixtures.source_transport import SOURCES, FixtureTransport
from tests.integration.conftest import API, TEST_S2_KEY, create_project

pytestmark = pytest.mark.integration

ARXIV, CROSSREF, S2, OA = (
    "export.arxiv.org",
    "api.crossref.org",
    "api.semanticscholar.org",
    "api.openalex.org",
)


@pytest.fixture
def keyed(settings: Settings) -> Settings:
    return settings.model_copy(update={"s2_api_key": SecretStr(TEST_S2_KEY)})


async def drain(settings: Settings, transport: FixtureTransport) -> None:
    """Run the worker until no job is ready."""
    worker, close = await build_worker(
        settings, source_transport=transport, source_rate_limits=False
    )
    try:
        while await worker.tick():
            pass
    finally:
        await close()


async def project_with_objective(client: httpx.AsyncClient, **overrides: Any) -> str:
    project_id = await create_project(client)
    resp = await client.post(
        f"{API}/projects/{project_id}/objective", json={**OBJECTIVE, **overrides}
    )
    assert resp.status_code == 201, resp.text
    return project_id


async def start(client: httpx.AsyncClient, project_id: str, **config: Any) -> str:
    resp = await client.post(
        f"{API}/projects/{project_id}/discovery-runs", json={**RUN_CONFIG, **config}
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["objective_version"] >= 1
    return str(resp.json()["id"])


async def get(client: httpx.AsyncClient, path: str) -> Any:
    resp = await client.get(f"{API}{path}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def statuses(searches: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    return {(s["plan_query_id"], s["source"]): s["status"] for s in searches}


RECORDED = {
    **{(q, "arxiv_api"): "succeeded" for q in ("Q1", "Q2", "Q3", "Q4")},
    **{(q, "crossref"): "succeeded" for q in ("Q1", "Q2", "Q3", "Q4")},
    ("Q1", "semantic_scholar"): "failed",
    ("Q2", "semantic_scholar"): "succeeded",
    ("Q3", "semantic_scholar"): "failed",
    ("Q4", "semantic_scholar"): "skipped",
    ("Q1", "openalex"): "budget_exhausted",
    **{(q, "openalex"): "skipped" for q in ("Q2", "Q3", "Q4")},
}


async def test_end_to_end_discovery_with_recorded_responses(
    authenticated_client: httpx.AsyncClient,
    keyed: Settings,
    sources_transport: FixtureTransport,
    migrated_db: str,
) -> None:
    client = authenticated_client
    project_id = await project_with_objective(client)
    run_id = await start(client, project_id, confirm_plan=True)

    # 1. The plan is prepared and shown; nothing is searched before the user agrees.
    await drain(keyed, sources_transport)
    run = await get(client, f"/runs/{run_id}")
    assert (run["status"], run["objective_version"]) == ("awaiting_approval", 1)
    [checkpoint] = await get(client, f"/runs/{run_id}/checkpoints")
    assert checkpoint["name"] == "confirm_search_plan"
    assert "protein folding" in checkpoint["payload"]["question"]
    assert sources_transport.requests == []
    plan = await get(client, f"/runs/{run_id}/discovery/plan")
    assert plan["objective_version"] == 1 and len(plan["plan"]["queries"]) == 4
    assert plan["plan"]["sub_question_queries"] == {"SQ1": ["Q2"], "SQ2": ["Q3"]}

    resp = await client.post(
        f"{API}/checkpoints/{checkpoint['id']}/decision", json={"status": "approved"}
    )
    assert resp.status_code == 202
    await drain(keyed, sources_transport)

    # 2. Searches: every source, recorded outcome per query; failures do not stop the run.
    run = await get(client, f"/runs/{run_id}")
    assert run["status"] == "partially_succeeded"
    searches = (await get(client, f"/runs/{run_id}/discovery/searches"))["searches"]
    assert statuses(searches) == RECORDED
    for s in searches:
        if s["status"] == "succeeded":
            assert s["result_count"] == 5 and s["total_available"] and s["executed_at"]
        if s["status"] in ("failed", "budget_exhausted"):
            assert s["error"]["upstream_status"] == 429
    # Retries: a 429 with a key is retried (4 attempts); a failing source is not asked a
    # third time; OpenAlex's exhausted budget is not asked again.
    # 4 searches + one batched lookup of the arXiv IDs Semantic Scholar found.
    assert sources_transport.count(ARXIV) == 5
    lookups = [r for r in sources_transport.requests if "id_list" in r.url.params]
    assert [r.url.params["id_list"] for r in lookups] == ["2602.22405,2505.01912"]
    assert sources_transport.count(S2) == 4 + 1 + 4
    assert sources_transport.count(OA) == 1
    sources = await get(client, f"/runs/{run_id}/discovery/sources")
    states = {s["source"]: s["state"] for s in sources["sources"]}
    assert states == {
        "arxiv_api": "ok",
        "crossref": "ok",
        "semantic_scholar": "partial",
        "openalex": "budget_exhausted",
    }
    assert {c["source"] for c in sources["not_searched"]} == {"biorxiv_api", "medrxiv_api"}

    # 3. Papers: real works only, with provenance, dates, release types and the version used.
    papers = (await get(client, f"/runs/{run_id}/discovery/papers"))["papers"]
    assert len(papers) == 12
    assert all(p["objective_version"] == 1 and p["added_by_this_run"] for p in papers)
    assert {s for p in papers for s in p["found_in_sources"]} == {
        "arxiv_api",
        "crossref",
        "semantic_scholar",
    }
    assert {k for p in papers for k in p["sub_question_keys"]} == {"SQ1", "SQ2"}
    releases = {r.value for r in ReleaseType}
    assert all(p["release_type"] in releases for p in papers)
    summary = await get(client, f"/runs/{run_id}/discovery/summary")
    assert (summary["objective_version"], summary["status"]) == (1, "partially_succeeded")
    assert summary["papers"]["added"] == 12
    assert summary["searches"]["succeeded"] == 9 and summary["searches"]["planned"] == 16
    assert sum(summary["date_confidence"].values()) == 12
    assert summary["version_matching"]["merges"] == 1  # one decisive/strong auto-match
    assert all(c["papers"] > 0 for c in summary["sub_question_coverage"].values())
    assert summary["hits"]["duplicate"] >= 1

    with psycopg.connect(migrated_db) as conn:
        items = conn.execute(
            "SELECT item_id, discovered_via, discovered_in_run_id, objective_version, "
            "relation_uid FROM project_items WHERE project_id = %s",
            (project_id,),
        ).fetchall()
        assert len(items) == 12
        for item_id, via, in_run, version, edge in items:
            assert (via, str(in_run), version) == ("search", run_id, 1)
            assert edge == relation_uid(
                "IN_PROJECT", "project_items", item_id, uuid.UUID(project_id)
            )
        # Every hit points at the source record it came from; every work's dates too.
        assert conn.execute(
            "SELECT count(*) FROM search_results r JOIN search_queries q ON q.id = r.query_id "
            "WHERE q.run_id = %s AND r.source_record_id IS NULL",
            (run_id,),
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM paper_dates d JOIN project_items pi ON pi.item_id = d.paper_id "
            "WHERE pi.project_id = %s AND d.source_record_id IS NULL "
            "AND d.event <> 'first_seen_by_researchpilot'",
            (project_id,),
        ).fetchone() == (0,)
        # "Verified" only from a primary event of a system of record.
        assert conn.execute(
            "SELECT count(*) FROM papers p JOIN project_items pi ON pi.item_id = p.id "
            "JOIN paper_dates d ON d.id = p.first_public_event_id WHERE pi.project_id = %s "
            "AND p.date_confidence = 'verified' AND NOT d.is_primary",
            (project_id,),
        ).fetchone() == (0,)
        hits_before = conn.execute(
            "SELECT count(*) FROM search_results r JOIN search_queries q ON q.id = r.query_id "
            "WHERE q.run_id = %s",
            (run_id,),
        ).fetchone()

    # 4. Retrying the partial run re-sends only what failed; nothing is duplicated.
    counts = {h: sources_transport.count(h) for h in (ARXIV, CROSSREF, S2, OA)}
    resp = await client.post(f"{API}/runs/{run_id}/retry")
    assert resp.status_code == 202
    await drain(keyed, sources_transport)
    assert (await get(client, f"/runs/{run_id}"))["status"] == "partially_succeeded"
    assert sources_transport.count(ARXIV) == counts[ARXIV]
    assert sources_transport.count(CROSSREF) == counts[CROSSREF]
    assert sources_transport.count(S2) == counts[S2] + 4 + 4  # Q1 and Q3 again; Q4 skipped
    again = await get(client, f"/runs/{run_id}/discovery/summary")
    assert again["papers"] == summary["papers"]
    with psycopg.connect(migrated_db) as conn:
        assert conn.execute(
            "SELECT count(*) FROM project_items WHERE project_id = %s", (project_id,)
        ).fetchone() == (12,)
        assert (
            conn.execute(
                "SELECT count(*) FROM search_results r JOIN search_queries q ON q.id = r.query_id "
                "WHERE q.run_id = %s",
                (run_id,),
            ).fetchone()
            == hits_before
        )
    resp = await client.post(f"{API}/runs/{run_id}/retry")
    assert resp.status_code == 202  # still partial: may be retried again
    await drain(keyed, sources_transport)  # leave no queued job behind


async def test_rejecting_or_cancelling_at_the_plan_searches_nothing(
    authenticated_client: httpx.AsyncClient,
    keyed: Settings,
    sources_transport: FixtureTransport,
) -> None:
    client = authenticated_client
    project_id = await project_with_objective(client)
    run_id = await start(client, project_id, confirm_plan=True)
    await drain(keyed, sources_transport)
    [checkpoint] = await get(client, f"/runs/{run_id}/checkpoints")
    await client.post(f"{API}/checkpoints/{checkpoint['id']}/decision", json={"status": "rejected"})
    await drain(keyed, sources_transport)
    assert (await get(client, f"/runs/{run_id}"))["status"] == "cancelled"
    searches = (await get(client, f"/runs/{run_id}/discovery/searches"))["searches"]
    assert {s["status"] for s in searches} == {"pending"}

    second = await start(client, project_id, confirm_plan=True)
    await drain(keyed, sources_transport)
    assert (await client.post(f"{API}/runs/{second}/cancel")).status_code == 202
    await drain(keyed, sources_transport)
    assert (await get(client, f"/runs/{second}"))["status"] == "cancelled"
    assert sources_transport.requests == []
    assert (await client.post(f"{API}/runs/{second}/retry")).status_code == 409


async def test_the_run_keeps_the_objective_version_it_started_with(
    authenticated_client: httpx.AsyncClient,
    keyed: Settings,
    sources_transport: FixtureTransport,
    migrated_db: str,
) -> None:
    client = authenticated_client
    project_id = await project_with_objective(client)
    run_id = await start(client, project_id, confirm_plan=True)
    await drain(keyed, sources_transport)
    current = await get(client, f"/projects/{project_id}/objective")
    body = {k: current[k] for k in OBJECTIVE if k != "sub_questions"} | {
        "sub_questions": [{"key": s["key"], "text": s["text"]} for s in current["sub_questions"]],
        "base_version": 1,
        "notes": "edited while the search plan waits",
    }
    assert (
        await client.put(f"{API}/projects/{project_id}/objective", json=body)
    ).status_code == 201
    [checkpoint] = await get(client, f"/runs/{run_id}/checkpoints")
    await client.post(f"{API}/checkpoints/{checkpoint['id']}/decision", json={"status": "approved"})
    await drain(keyed, sources_transport)
    assert (await get(client, f"/runs/{run_id}"))["objective_version"] == 1
    assert (await get(client, f"/runs/{run_id}/discovery/summary"))["objective_version"] == 1
    preview = await get(client, f"/projects/{project_id}/discovery/plan-preview")
    assert preview["objective_version"] == 2 and preview["run_id"] is None
    with psycopg.connect(migrated_db) as conn:
        versions = conn.execute(
            "SELECT DISTINCT objective_version FROM project_items WHERE project_id = %s",
            (project_id,),
        ).fetchall()
    assert versions == [(1,)]


async def test_a_failing_source_does_not_lose_other_results(
    authenticated_client: httpx.AsyncClient,
    keyed: Settings,
    sources_transport: FixtureTransport,
    migrated_db: str,
) -> None:
    sources_transport.overrides[ARXIV] = lambda r: httpx.Response(503, text="unavailable")
    client = authenticated_client
    project_id = await project_with_objective(client)
    run_id = await start(client, project_id)
    await drain(keyed, sources_transport)
    assert (await get(client, f"/runs/{run_id}"))["status"] == "partially_succeeded"
    searches = (await get(client, f"/runs/{run_id}/discovery/searches"))["searches"]
    arxiv = {s["plan_query_id"]: s for s in searches if s["source"] == "arxiv_api"}
    assert [arxiv[q]["status"] for q in ("Q1", "Q2", "Q3", "Q4")] == [
        "failed",
        "failed",
        "skipped",
        "skipped",
    ]
    assert arxiv["Q1"]["error"]["upstream_status"] == 503
    sources = await get(client, f"/runs/{run_id}/discovery/sources")
    assert {s["source"]: s["state"] for s in sources["sources"]}["arxiv_api"] == "unavailable"
    # Each failed search was retried (4 attempts); then arXiv was left alone for this run,
    # apart from fetching the arXiv IDs other sources found (which fails and is recorded).
    search_requests = [
        r
        for r in sources_transport.requests
        if r.url.host == ARXIV and "search_query" in r.url.params
    ]
    assert len(search_requests) == 8
    papers = (await get(client, f"/runs/{run_id}/discovery/papers"))["papers"]
    assert papers and all("arxiv_api" not in p["found_in_sources"] for p in papers)
    # The other sources still fill the run; every hit is decided (none left pending).
    summary = await get(client, f"/runs/{run_id}/discovery/summary")
    assert summary["papers"]["added"] == 12
    assert "pending" not in summary["hits"]


async def test_a_crash_mid_run_resumes_without_repeating_work(
    authenticated_client: httpx.AsyncClient,
    keyed: Settings,
    sources_transport: FixtureTransport,
    migrated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}
    real = resolve.relation_writer.add_to_project

    async def crash_once(*args: Any, **kwargs: Any) -> bool:
        calls["n"] += 1
        if calls["n"] == 5:
            raise RuntimeError("worker lost (simulated)")
        return await real(*args, **kwargs)

    monkeypatch.setattr(resolve.relation_writer, "add_to_project", crash_once)
    client = authenticated_client
    project_id = await project_with_objective(client)
    run_id = await start(client, project_id)
    await drain(keyed, sources_transport)
    assert (await get(client, f"/runs/{run_id}"))["status"] == "running"
    counts = {h: sources_transport.count(h) for h in (ARXIV, CROSSREF, S2, OA)}
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        assert conn.execute(
            "SELECT count(*) FROM project_items WHERE project_id = %s", (project_id,)
        ).fetchone() == (4,)
        conn.execute("UPDATE jobs SET run_after = now() WHERE status = 'queued'")
    await drain(keyed, sources_transport)

    assert (await get(client, f"/runs/{run_id}"))["status"] == "partially_succeeded"
    events = [e["type"] for e in await get(client, f"/runs/{run_id}/events/log")]
    assert "run.resumed" in events
    # Searches were not sent again; every hit was decided exactly once.
    assert {h: sources_transport.count(h) for h in (ARXIV, S2, OA)} == {
        h: counts[h] for h in (ARXIV, S2, OA)
    }
    summary = await get(client, f"/runs/{run_id}/discovery/summary")
    assert summary["papers"]["added"] == 12
    with psycopg.connect(migrated_db) as conn:
        assert conn.execute(
            "SELECT count(*) FROM project_items WHERE project_id = %s", (project_id,)
        ).fetchone() == (12,)
        assert conn.execute(
            "SELECT count(*) FROM search_results r JOIN search_queries q ON q.id = r.query_id "
            "WHERE q.run_id = %s AND r.outcome = 'pending'",
            (run_id,),
        ).fetchone() == (0,)


async def test_exclusions_are_applied_and_recorded(
    authenticated_client: httpx.AsyncClient,
    keyed: Settings,
    sources_transport: FixtureTransport,
    migrated_db: str,
) -> None:
    client = authenticated_client
    project_id = await project_with_objective(client, exclusions=["sparsity"])
    run_id = await start(client, project_id, sources=["crossref"])
    await drain(keyed, sources_transport)
    assert (await get(client, f"/runs/{run_id}"))["status"] == "succeeded"
    with psycopg.connect(migrated_db) as conn:
        excluded = conn.execute(
            "SELECT r.title, r.outcome_detail, r.item_id FROM search_results r "
            "JOIN search_queries q ON q.id = r.query_id WHERE q.run_id = %s "
            "AND r.outcome = 'excluded'",
            (run_id,),
        ).fetchall()
        titles = conn.execute(
            "SELECT p.title FROM project_items pi JOIN papers p ON p.id = pi.item_id "
            "WHERE pi.project_id = %s",
            (project_id,),
        ).fetchall()
    assert sorted(excluded) == [
        (
            "Cardinality-Preserving Structured Sparse Graph Transformers for Molecular "
            "Property Prediction",
            "mentions excluded topic: sparsity",
            None,
        ),
        ("Molecular-Property Prediction with Sparsity", "mentions excluded topic: sparsity", None),
    ]
    assert all("sparsity" not in t.lower() for (t,) in titles)
    assert {
        s["source"] for s in (await get(client, f"/runs/{run_id}/discovery/sources"))["sources"]
    } == {"crossref"}


async def test_isolation_authorization_and_start_rules(
    authenticated_client: httpx.AsyncClient,
    keyed: Settings,
    sources_transport: FixtureTransport,
    migrated_db: str,
) -> None:
    client = authenticated_client
    no_objective = await create_project(client)
    resp = await client.post(f"{API}/projects/{no_objective}/discovery-runs", json={})
    assert resp.status_code == 422
    project_id = await project_with_objective(client)
    bad = await client.post(
        f"{API}/projects/{project_id}/discovery-runs", json={"sources": ["biorxiv_api"]}
    )
    assert bad.status_code == 422
    run_id = await start(client, project_id, confirm_plan=True)
    second = await client.post(f"{API}/projects/{project_id}/discovery-runs", json={})
    assert second.status_code == 409
    generic = await client.post(
        f"{API}/projects/{project_id}/runs", json={"workflow": "discovery", "config": {}}
    )
    assert generic.status_code == 409  # the generic endpoint applies the same rules
    await drain(keyed, sources_transport)

    # Another user's project and run are invisible.
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        other_user, other_project = uuid7(), uuid7()
        conn.execute(
            "INSERT INTO users (id, display_name, auth_provider) VALUES (%s, 'x', 'password')",
            (other_user,),
        )
        conn.execute(
            "INSERT INTO projects (id, user_id, title, topic, expertise_level, goal) "
            "VALUES (%s, %s, 't', 't', 'beginner', 'find_gap')",
            (other_project, other_user),
        )
        conn.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (%s, %s, 'owner')",
            (other_project, other_user),
        )
        other_run = uuid7()
        conn.execute(
            "INSERT INTO research_runs (id, project_id, workflow, status) "
            "VALUES (%s, %s, 'discovery', 'partially_succeeded')",
            (other_run, other_project),
        )
    for path in ("plan", "searches", "sources", "papers", "summary"):
        assert (await client.get(f"{API}/runs/{other_run}/discovery/{path}")).status_code == 404
    assert (await client.post(f"{API}/runs/{other_run}/retry")).status_code == 404
    # The user's own run is readable.
    assert (await client.get(f"{API}/runs/{run_id}/discovery/plan")).status_code == 200
    assert (
        await client.post(f"{API}/projects/{other_project}/discovery-runs", json={})
    ).status_code == 404
    # Viewers can read but not start.
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute(
            "UPDATE project_members SET role = 'viewer' WHERE project_id = %s", (project_id,)
        )
    resp = await client.post(f"{API}/projects/{project_id}/discovery-runs", json={})
    assert resp.status_code == 403
    assert (
        await client.get(f"{API}/projects/{project_id}/discovery/plan-preview")
    ).status_code == 200


async def test_citations_come_only_from_source_metadata_through_relation_writer(
    authenticated_client: httpx.AsyncClient, settings: Settings, migrated_db: str
) -> None:
    """A recorded OpenAlex work (ResNet, CVPR) lists the works it cites; CITES is written for
    the cited works we hold - never for others - as global source metadata."""
    client = authenticated_client
    project_id = await project_with_objective(client)
    run_id = await start(client, project_id, confirm_plan=True)
    work = json.loads((SOURCES / "openalex" / "works_doi_10.1109_cvpr.2016.90.json").read_text())
    cited_ids = [r.rsplit("/", 1)[-1] for r in work["referenced_works"][:2]]
    sessions = make_sessionmaker(make_engine(settings.database_url))
    record = await SourceRecordStore(sessions).save(
        SourceName.OPENALEX,
        work["id"].rsplit("/", 1)[-1],
        "works",
        work,
        datetime.now(UTC),
    )
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        papers = []
        for oa_id in [work["id"].rsplit("/", 1)[-1], *cited_ids, "W0000000001"]:
            pid = uuid7()
            conn.execute("INSERT INTO research_items (id, item_type) VALUES (%s, 'paper')", (pid,))
            conn.execute(
                "INSERT INTO papers (id, title, normalized_title) VALUES (%s, %s, %s)",
                (pid, oa_id, oa_id.lower()),
            )
            mid = uuid7()
            conn.execute(
                "INSERT INTO paper_manifestations (id, paper_id, kind, server_or_venue, "
                "primary_identifier_scheme, primary_identifier_value, peer_review_label) "
                "VALUES (%s, %s, 'other', 'OpenAlex', 'openalex', %s, 'unknown')",
                (mid, pid, oa_id),
            )
            conn.execute(
                "INSERT INTO paper_identifiers (id, paper_id, manifestation_id, scheme, value, "
                "source) VALUES (%s, %s, %s, 'openalex', %s, 'openalex')",
                (uuid7(), pid, mid, oa_id),
            )
            papers.append(pid)
        citing, *cited, unrelated = papers
        query = uuid7()
        conn.execute(
            "INSERT INTO search_queries (id, run_id, plan_query_id, source, query_text, origin, "
            "status) VALUES (%s, %s, 'Q1', 'openalex', 'residual learning', 'planner', "
            "'succeeded') ON CONFLICT DO NOTHING",
            (query, run_id),
        )
        query = conn.execute(
            "SELECT id FROM search_queries WHERE run_id = %s AND plan_query_id = 'Q1' "
            "AND source = 'openalex'",
            (run_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO search_results (query_id, rank, source_record_id, source_item_id, "
            "item_id, outcome) VALUES (%s, 1, %s, %s, %s, 'added')",
            (query, record, work["id"], citing),
        )
    first = await relate.write_citations(sessions, uuid.UUID(run_id))
    second = await relate.write_citations(sessions, uuid.UUID(run_id))
    assert first == {"created": 2, "existing": 0, "suppressed": 0}
    assert second == {"created": 0, "existing": 2, "suppressed": 0}
    with psycopg.connect(migrated_db) as conn:
        rows = conn.execute(
            "SELECT cited_id, assertion, scope_project_id, evidence, provenance, relation_uid "
            "FROM citations WHERE citing_id = %s",
            (citing,),
        ).fetchall()
    assert {r[0] for r in rows} == set(cited) and unrelated not in {r[0] for r in rows}
    for cited_id, assertion, scope, evidence, provenance, uid in rows:
        assert (assertion, scope) == ("source_metadata", None)
        assert evidence == {"source_record_ids": [str(record)]}
        assert provenance["service"] == "discovery-w1"
        assert provenance["source_api"] == "openalex"
        assert provenance["project_context"] is False
        assert uid == relation_uid("CITES", "citations", citing, cited_id)


async def test_possible_matches_are_reported_and_never_merged(
    client: httpx.AsyncClient, settings: Settings, migrated_db: str
) -> None:
    """ResNet on arXiv and at CVPR: same title and authors, no identifier link -> a possible
    match. A discovery summary lists it for review; nothing is merged."""
    project_id = await create_project(client)
    ids = []
    for identifier in ("1512.03385", "10.1109/cvpr.2016.90"):
        resp = await client.post(
            f"{API}/projects/{project_id}/papers", json={"identifier": identifier}
        )
        ids.append(uuid.UUID(resp.json()["id"]))
    sessions = make_sessionmaker(make_engine(settings.database_url))
    async with session_scope(sessions) as session:
        found = await summary_mod.possible_matches(session, ids)
    assert len(found) == 1 and {found[0]["paper_a"], found[0]["paper_b"]} == set(ids)
    with psycopg.connect(migrated_db) as conn:
        merged = conn.execute(
            "SELECT count(*) FROM papers WHERE id = ANY(%s) AND merged_into_id IS NOT NULL",
            (ids,),
        ).fetchone()
    assert merged == (0,)
