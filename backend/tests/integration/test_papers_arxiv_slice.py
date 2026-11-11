"""M1a slice 1: arXiv identifier -> work, manifestation, identifiers, date events, resolved date.

Uses recorded arXiv responses (tests/fixtures/sources/arxiv, recorded 2026-11-11).
"""

from __future__ import annotations

import httpx
import psycopg
import pytest
import sqlalchemy as sa

from researchpilot.core.settings import Settings
from researchpilot.db.session import make_engine, make_sessionmaker
from researchpilot.domain.enums import SourceName
from researchpilot.integrations.base import PostgresRateLimiter
from tests.fixtures.source_transport import SOURCES, FixtureTransport
from tests.integration.conftest import API, create_project

pytestmark = pytest.mark.integration

V1_SUBMITTED = "2017-06-12T17:57:34Z"
V7_SUBMITTED = "2023-08-02T00:41:18Z"


async def add(client: httpx.AsyncClient, project_id: str, identifier: str) -> httpx.Response:
    return await client.post(f"{API}/projects/{project_id}/papers", json={"identifier": identifier})


async def test_add_arxiv_paper_end_to_end(
    client: httpx.AsyncClient, sources_transport: FixtureTransport
) -> None:
    project_id = await create_project(client)
    created = await add(client, project_id, "https://arxiv.org/abs/1706.03762v2")
    assert created.status_code == 201, created.text
    paper_id = created.json()["id"]

    detail = (await client.get(f"{API}/projects/{project_id}/papers/{paper_id}")).json()
    assert detail["title"] == "Attention Is All You Need"
    assert detail["fields_of_study"] == ["cs.CL", "cs.LG"]

    [manifestation] = detail["manifestations"]
    assert manifestation["kind"] == "preprint"
    assert manifestation["server_or_venue"] == "arxiv"
    assert manifestation["peer_review_label"] == "preprint_not_peer_reviewed"
    assert detail["identifiers"] == [
        {
            "manifestation_id": manifestation["id"],
            "scheme": "arxiv",
            "value": "1706.03762",
            "version": 7,
            "source": "arxiv_api",
        }
    ]
    assert [a["raw_name"] for a in detail["authors"]][:2] == ["Ashish Vaswani", "Noam Shazeer"]

    events = {(d["event"], d["version"]): d for d in detail["dates"]}
    assert set(events) == {
        ("preprint_submitted", 1),
        ("version_submitted", 7),
        ("first_seen_by_researchpilot", None),
    }
    v1 = events[("preprint_submitted", 1)]
    assert v1["value"].replace("+00:00", "Z") == V1_SUBMITTED
    assert (v1["is_primary"], v1["reporting_source"], v1["upstream_source"]) == (
        True,
        "arxiv_api",
        "arxiv",
    )
    assert v1["upstream_evidence"]["field"] == "atom:entry/published"
    assert v1["source_record_id"] is not None and v1["retrieved_at"]
    assert events[("version_submitted", 7)]["value"].replace("+00:00", "Z") == V7_SUBMITTED
    assert events[("first_seen_by_researchpilot", None)]["is_primary"] is False

    # No announcement captured yet: the submission time is used, labelled submission_only.
    resolved = detail["resolved_date"]
    assert resolved["confidence"] == "verified"
    assert resolved["basis"] == "submission_only"
    assert resolved["event_id"] == v1["id"]
    assert resolved["first_public_appearance"].replace("+00:00", "Z") == V1_SUBMITTED
    assert resolved["candidate_public_date"] is None

    listing = (await client.get(f"{API}/projects/{project_id}/papers")).json()
    assert [p["id"] for p in listing] == [paper_id]
    assert listing[0]["discovered_via"] == "manual"
    assert sources_transport.count("export.arxiv.org") == 1


async def test_same_work_is_reused_and_not_refetched(
    client: httpx.AsyncClient, sources_transport: FixtureTransport, db: psycopg.Connection
) -> None:
    first_project = await create_project(client)
    paper_id = (await add(client, first_project, "1706.03762")).json()["id"]

    again = await add(client, first_project, "arXiv:1706.03762v7")
    assert (again.status_code, again.json()) == (200, {"id": paper_id, "added_to_project": False})
    # The arXiv-assigned DataCite DOI identifies the same work.
    second_project = await create_project(client)
    via_doi = await add(client, second_project, "https://doi.org/10.48550/arXiv.1706.03762")
    assert (via_doi.status_code, via_doi.json()["id"]) == (201, paper_id)

    assert sources_transport.count("export.arxiv.org") == 1  # known identifiers: no request
    assert db.execute("SELECT count(*) FROM papers").fetchone() == (1,)
    assert db.execute("SELECT count(*) FROM paper_manifestations").fetchone() == (1,)
    # The work and its version are global graph nodes.
    assert db.execute(
        "SELECT kind, scope_project_id FROM graph_nodes WHERE kind IN ('Paper', 'PaperVersion') "
        "ORDER BY kind"
    ).fetchall() == [("Paper", None), ("PaperVersion", None)]


async def test_old_style_identifier_with_journal_link(
    client: httpx.AsyncClient, db: psycopg.Connection
) -> None:
    project_id = await create_project(client)
    resp = await add(client, project_id, "arXiv:hep-th/9711200v2")  # queried without version
    assert resp.status_code == 201, resp.text
    detail = (await client.get(f"{API}/projects/{project_id}/papers/{resp.json()['id']}")).json()
    assert detail["identifiers"][0]["value"] == "hep-th/9711200"
    # The author-supplied journal DOI is kept in the raw record for the Version Matcher;
    # it is not an identifier of the arXiv manifestation.
    assert {i["scheme"] for i in detail["identifiers"]} == {"arxiv"}
    [payload] = db.execute(
        "SELECT payload->>'entry_xml' FROM source_records WHERE source = 'arxiv_api' "
        "AND source_entity_id = 'hep-th/9711200v3'"
    ).fetchone() or [None]
    assert "10.1023/A:1026654312961" in str(payload)


async def test_unknown_and_unsupported_identifiers(client: httpx.AsyncClient) -> None:
    project_id = await create_project(client)
    missing = await add(client, project_id, "2401.99999")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.json()["code"] == "source_not_found"

    doi = await add(client, project_id, "10.1038/nature14539")
    assert doi.status_code == 501
    assert doi.json()["code"] == "capability_unavailable"

    invalid = await add(client, project_id, "not a paper")
    assert invalid.status_code == 422


async def test_arxiv_error_entries_become_source_errors(
    client: httpx.AsyncClient, sources_transport: FixtureTransport
) -> None:
    error_feed = (SOURCES / "arxiv" / "api_hep-th_9711200v2.xml").read_text()
    sources_transport.overrides["export.arxiv.org"] = lambda r: httpx.Response(200, text=error_feed)
    project_id = await create_project(client)
    resp = await add(client, project_id, "1706.03762")
    assert resp.status_code == 503
    assert resp.json()["code"] == "source_unavailable"


async def test_papers_from_other_projects_are_not_visible(client: httpx.AsyncClient) -> None:
    mine = await create_project(client)
    other = await create_project(client)
    paper_id = (await add(client, mine, "1706.03762")).json()["id"]
    assert (await client.get(f"{API}/projects/{other}/papers/{paper_id}")).status_code == 404


async def test_source_records_are_stored_once_per_content(
    client: httpx.AsyncClient, db: psycopg.Connection
) -> None:
    project_id = await create_project(client)
    await add(client, project_id, "1706.03762")
    db.execute("DELETE FROM project_items; DELETE FROM papers; DELETE FROM research_items")
    db.execute("DELETE FROM http_cache")  # force a second, identical response
    db.commit()
    await add(client, project_id, "1706.03762")
    assert db.execute(
        "SELECT count(*) FROM source_records WHERE source = 'arxiv_api'"
    ).fetchone() == (1,)


async def test_first_public_invariants_are_enforced(
    client: httpx.AsyncClient, db: psycopg.Connection
) -> None:
    project_id = await create_project(client)
    paper_id = (await add(client, project_id, "1706.03762")).json()["id"]
    v7 = db.execute(
        "SELECT id, value FROM paper_dates WHERE paper_id = %s AND event = 'version_submitted'",
        (paper_id,),
    ).fetchone()
    assert v7 is not None
    with pytest.raises(psycopg.errors.CheckViolation, match="cannot be a first public"):
        db.execute(
            "UPDATE papers SET first_public_event_id = %s, first_public_appearance = %s "
            "WHERE id = %s",
            (v7[0], v7[1], paper_id),
        )
    db.rollback()
    with pytest.raises(psycopg.errors.CheckViolation, match="verified or corroborated"):
        db.execute("UPDATE papers SET date_confidence = 'single_source' WHERE id = %s", (paper_id,))
    db.rollback()


async def test_postgres_rate_limiter_spaces_requests_across_processes(
    settings: Settings,
) -> None:
    """Two limiter instances (as in the API and the worker) share one slot sequence."""
    engine = make_engine(settings.database_url)
    try:
        waits: list[float] = []

        async def record(seconds: float) -> None:
            waits.append(seconds)

        sessions = make_sessionmaker(engine)
        api, worker = PostgresRateLimiter(sessions, record), PostgresRateLimiter(sessions, record)
        for limiter in (api, worker, api):
            await limiter.acquire(SourceName.ARXIV_API, 3.0)
        async with sessions() as session:
            next_slot = (
                await session.execute(
                    sa.text(
                        "SELECT next_slot_at - now() FROM source_rate_limits WHERE source = 'arxiv_api'"
                    )
                )
            ).scalar_one()
    finally:
        await engine.dispose()
    assert len(waits) == 2  # the first request goes immediately
    assert 2.5 < waits[0] <= 3.0 and 5.5 < waits[1] <= 6.0
    assert 8.5 < next_slot.total_seconds() <= 9.0
