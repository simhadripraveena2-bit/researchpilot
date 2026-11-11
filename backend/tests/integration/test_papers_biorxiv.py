"""bioRxiv/medRxiv: server API is the system of record for posting dates (D22)."""

from __future__ import annotations

import httpx
import psycopg
import pytest

from tests.fixtures.source_transport import FixtureTransport
from tests.integration.conftest import API, create_project

pytestmark = pytest.mark.integration


async def add(client: httpx.AsyncClient, project_id: str, identifier: str) -> httpx.Response:
    return await client.post(f"{API}/projects/{project_id}/papers", json={"identifier": identifier})


async def detail(client: httpx.AsyncClient, project_id: str, paper_id: str) -> dict:  # type: ignore[type-arg]
    return dict((await client.get(f"{API}/projects/{project_id}/papers/{paper_id}")).json())


def preprint_manifestation(d: dict) -> dict:  # type: ignore[type-arg]
    [m] = [m for m in d["manifestations"] if m["kind"] == "preprint"]
    return dict(m)


async def test_biorxiv_preprint_versions_and_verified_posting_date(
    client: httpx.AsyncClient,
) -> None:
    project_id = await create_project(client)
    resp = await add(client, project_id, "https://doi.org/10.1101/2022.10.22.513336")
    assert resp.status_code == 201, resp.text
    d = await detail(client, project_id, resp.json()["id"])
    m = preprint_manifestation(d)
    assert (m["server_or_venue"], m["peer_review_label"]) == (
        "biorxiv",
        "preprint_not_peer_reviewed",
    )
    posted = sorted(
        (e["event"], e["version"], e["value"][:10])
        for e in d["dates"]
        if e["reporting_source"] == "biorxiv_api"
    )
    assert posted == [
        ("preprint_posted", 1, "2022-10-22"),
        ("version_posted", 2, "2023-03-04"),
        ("version_posted", 3, "2023-11-26"),
    ]
    preprint_doi = next(i for i in d["identifiers"] if i["value"] == "10.1101/2022.10.22.513336")
    assert preprint_doi["version"] == 3
    # The eLife versions (followed from the stated links) are separate manifestations of the
    # same work. Their later journal date does not replace the verified preprint posting.
    assert {m["server_or_venue"] for m in d["manifestations"] if m["kind"] == "published"} == {
        "eLife"
    }
    r = d["resolved_date"]
    assert (r["confidence"], r["basis"], r["manifestation_id"]) == ("verified", "posted", m["id"])
    assert r["first_public_appearance"].startswith("2022-10-22")
    assert any(
        e["event"] == "published_online" and e["value"].startswith("2024-06-03") for e in d["dates"]
    )


async def test_medrxiv_preprint_is_looked_up_on_medrxiv_first(
    client: httpx.AsyncClient, sources_transport: FixtureTransport
) -> None:
    project_id = await create_project(client)
    resp = await add(client, project_id, "10.1101/2023.12.14.23299828")
    assert resp.status_code == 201, resp.text
    d = await detail(client, project_id, resp.json()["id"])
    assert {m["server_or_venue"] for m in d["manifestations"]} == {"medrxiv", "JAMA Pediatrics"}
    assert d["resolved_date"]["basis"] == "posted"
    assert d["resolved_date"]["first_public_appearance"].startswith("2023-12-15")
    assert [str(r.url) for r in sources_transport.requests] == [
        "https://api.biorxiv.org/details/medrxiv/10.1101/2023.12.14.23299828",
        "https://api.crossref.org/works/10.1001/jamapediatrics.2024.1379",
    ]


async def test_crossref_record_of_the_same_preprint_adds_secondary_events(
    client: httpx.AsyncClient, app: object, db: psycopg.Connection
) -> None:
    """Same DOI from bioRxiv and Crossref: one manifestation, both sources' events kept;
    the server's primary posting date stands."""
    from researchpilot.services.papers.ingest_crossref import ingest_crossref

    project_id = await create_project(client)
    paper_id = (await add(client, project_id, "10.1101/2022.10.22.513336")).json()["id"]
    sources = app.state.sources  # type: ignore[attr-defined]
    fetched = await sources.crossref.fetch("10.1101/2022.10.22.513336")
    async with app.state.sessions() as session, session.begin():  # type: ignore[attr-defined]
        result = await ingest_crossref(session, fetched)
    assert str(result.paper_id) == paper_id and not result.created
    d = await detail(client, project_id, paper_id)
    m = preprint_manifestation(d)
    seen = {
        (e["event"], e["reporting_source"], e["is_primary"])
        for e in d["dates"]
        if e["manifestation_id"] == m["id"]
    }
    assert ("preprint_posted", "biorxiv_api", True) in seen
    assert ("preprint_posted", "crossref", False) in seen
    assert d["resolved_date"]["basis"] == "posted"
    assert db.execute(
        "SELECT count(*) FROM paper_source_links WHERE manifestation_id = %s", (m["id"],)
    ).fetchone() == (2,)


async def test_api_outage_never_promotes_the_later_journal_date(
    client: httpx.AsyncClient, sources_transport: FixtureTransport
) -> None:
    """bioRxiv down: the preprint comes from Crossref (secondary posting date) and the eLife
    version is primary but later. The date is uncertain, not 'published 2024'."""
    sources_transport.overrides["api.biorxiv.org"] = lambda r: httpx.Response(502)
    project_id = await create_project(client)
    resp = await add(client, project_id, "10.1101/2022.10.22.513336")
    assert resp.status_code == 201, resp.text
    d = await detail(client, project_id, resp.json()["id"])
    r = d["resolved_date"]
    assert (r["confidence"], r["first_public_appearance"], r["candidate_public_date"]) == (
        "conflicting",
        None,
        "2022-10-22",
    )
    assert sources_transport.count("api.biorxiv.org") == 4  # retried, then gave up
