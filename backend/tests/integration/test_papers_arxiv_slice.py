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


def openalex_unknown(transport: FixtureTransport) -> None:
    """Simulates a paper OpenAlex does not have (real 404 shape: HTML body)."""
    transport.overrides["api.openalex.org"] = lambda r: httpx.Response(404, text="Not Found")


async def add(client: httpx.AsyncClient, project_id: str, identifier: str) -> httpx.Response:
    return await client.post(f"{API}/projects/{project_id}/papers", json={"identifier": identifier})


async def test_add_arxiv_paper_end_to_end(
    client: httpx.AsyncClient, sources_transport: FixtureTransport
) -> None:
    openalex_unknown(sources_transport)  # no secondary date: the submission-only path
    project_id = await create_project(client)
    created = await add(client, project_id, "https://arxiv.org/abs/1706.03762v2")
    assert created.status_code == 201, created.text
    paper_id = created.json()["id"]
    assert created.json()["coverage"] == {
        "openalex": "not_found",
        "semantic_scholar": "unavailable",
    }

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
    assert again.status_code == 200
    assert (again.json()["id"], again.json()["added_to_project"]) == (paper_id, False)
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
    # The author-supplied journal DOI is not an identifier of the arXiv manifestation: it is
    # a version link. Following it fetched the IJTP reprint, a separate manifestation that
    # the Version Matcher attached to the same work.
    by_manifestation = {m["id"]: m for m in detail["manifestations"]}
    arxiv_m = next(m for m in by_manifestation.values() if m["server_or_venue"] == "arxiv")
    published_m = next(m["id"] for m in by_manifestation.values() if m["kind"] == "published")
    found = {(i["scheme"], i["value"], i["manifestation_id"]) for i in detail["identifiers"]}
    assert ("arxiv", "hep-th/9711200", arxiv_m["id"]) in found
    assert ("doi", "10.1023/a:1026654312961", published_m) in found
    # OpenAlex has one work for both (W2166248051); its ID sits on the looked-up version.
    assert ("openalex", "W2166248051", published_m) in found
    # Only a month is known for the journal version, so no date can be confirmed (the
    # submission-only fallback does not apply once a public-availability claim exists).
    assert detail["resolved_date"]["confidence"] == "uncertain"
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

    pmid = await add(client, project_id, "PMID:32511466")
    assert pmid.status_code == 501
    assert pmid.json()["code"] == "capability_unavailable"
    # Semantic Scholar IDs resolve through Semantic Scholar, which refuses keyless requests.
    corpus = await add(client, project_id, "CorpusId:13756489")
    assert (corpus.status_code, corpus.json()["code"]) == (503, "source_unavailable")

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
    client: httpx.AsyncClient, db: psycopg.Connection, sources_transport: FixtureTransport
) -> None:
    openalex_unknown(sources_transport)  # keeps the paper on the submission-only path
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


async def test_real_public_event_replaces_submission_only_in_the_database(
    client: httpx.AsyncClient,
    db: psycopg.Connection,
    settings: Settings,
    sources_transport: FixtureTransport,
) -> None:
    """arXiv v1 submitted 2017-06-12 (no announcement captured), then a journal version
    published online later: the trigger refuses submission_only, the resolver picks the
    journal event, and the submission event is kept unchanged."""
    from datetime import UTC, datetime

    from researchpilot.core.ids import uuid7
    from researchpilot.services.dates.store import resolve_paper_dates

    openalex_unknown(sources_transport)
    project_id = await create_project(client)
    paper_id = (await add(client, project_id, "1706.03762")).json()["id"]
    submission_before = db.execute(
        "SELECT id, value, flags FROM paper_dates WHERE paper_id = %s "
        "AND event = 'preprint_submitted'",
        (paper_id,),
    ).fetchone()
    journal_m, online_id = uuid7(), uuid7()
    online = datetime(2017, 12, 4, tzinfo=UTC)
    db.execute(
        "INSERT INTO paper_manifestations (id, paper_id, kind, server_or_venue, "
        "primary_identifier_scheme, primary_identifier_value, peer_review_label) "
        "VALUES (%s, %s, 'published', 'NeurIPS', 'doi', '10.5555/example', 'journal_version')",
        (journal_m, paper_id),
    )
    db.execute(
        "INSERT INTO paper_dates (id, paper_id, manifestation_id, event, value, precision, "
        "is_primary, reporting_source, upstream_source, retrieved_at) VALUES "
        "(%s, %s, %s, 'published_online', %s, 'day', true, 'crossref', 'crossref', now())",
        (online_id, paper_id, journal_m, online),
    )
    with pytest.raises(psycopg.errors.CheckViolation, match="without any public-availability"):
        db.execute("UPDATE papers SET row_version = row_version WHERE id = %s", (paper_id,))
    db.rollback()

    # Same situation through the resolver (committed data, application session).
    db.execute(
        "INSERT INTO paper_manifestations (id, paper_id, kind, server_or_venue, "
        "primary_identifier_scheme, primary_identifier_value, peer_review_label) "
        "VALUES (%s, %s, 'published', 'NeurIPS', 'doi', '10.5555/example', 'journal_version')",
        (journal_m, paper_id),
    )
    db.execute(
        "INSERT INTO paper_dates (id, paper_id, manifestation_id, event, value, precision, "
        "is_primary, reporting_source, upstream_source, retrieved_at) VALUES "
        "(%s, %s, %s, 'published_online', %s, 'day', true, 'crossref', 'crossref', now())",
        (online_id, paper_id, journal_m, online),
    )
    db.commit()
    engine = make_engine(settings.database_url)
    try:
        async with make_sessionmaker(engine)() as session, session.begin():
            await resolve_paper_dates(session, paper_id, datetime.now(UTC))
    finally:
        await engine.dispose()

    resolved = (await client.get(f"{API}/projects/{project_id}/papers/{paper_id}")).json()
    assert resolved["resolved_date"]["basis"] == "published_online"
    assert resolved["resolved_date"]["event_id"] == str(online_id)
    assert resolved["resolved_date"]["confidence"] == "verified"
    assert (
        db.execute(
            "SELECT id, value, flags FROM paper_dates WHERE paper_id = %s "
            "AND event = 'preprint_submitted'",
            (paper_id,),
        ).fetchone()
        == submission_before
    )


async def test_openalex_date_makes_an_unannounced_arxiv_paper_unconfirmed(
    client: httpx.AsyncClient,
) -> None:
    """With OpenAlex's (secondary) publication date, the approved rule applies: a public
    claim exists, so submission_only is not used; the date is single-source, unconfirmed,
    until a primary event (e.g. a captured announcement) arrives. The submission is kept."""
    project_id = await create_project(client)
    created = await add(client, project_id, "1706.03762")
    assert created.json()["coverage"]["openalex"] == "ok"
    d = (await client.get(f"{API}/projects/{project_id}/papers/{created.json()['id']}")).json()
    reported = next(e for e in d["dates"] if e["event"] == "reported_publication_date")
    assert (reported["reporting_source"], reported["upstream_source"], reported["is_primary"]) == (
        "openalex",
        "unknown",
        False,
    )
    assert {"index_created", "metadata_updated", "preprint_submitted"} <= {
        e["event"] for e in d["dates"]
    }
    r = d["resolved_date"]
    assert (r["confidence"], r["first_public_appearance"], r["candidate_public_date"]) == (
        "single_source",
        None,
        "2017-06-12",
    )
