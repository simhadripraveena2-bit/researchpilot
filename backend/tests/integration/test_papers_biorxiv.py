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


async def test_biorxiv_preprint_versions_and_verified_posting_date(
    client: httpx.AsyncClient, sources_transport: FixtureTransport
) -> None:
    project_id = await create_project(client)
    resp = await add(client, project_id, "https://doi.org/10.1101/2022.10.22.513336")
    assert resp.status_code == 201, resp.text
    d = await detail(client, project_id, resp.json()["id"])
    [m] = d["manifestations"]
    assert (m["kind"], m["server_or_venue"], m["peer_review_label"]) == (
        "preprint",
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
    r = d["resolved_date"]
    assert (r["confidence"], r["basis"]) == ("verified", "posted")
    assert r["first_public_appearance"].startswith("2022-10-22")
    assert d["identifiers"][0]["version"] == 3
    assert sources_transport.count("api.crossref.org") == 0


async def test_medrxiv_preprint_is_looked_up_on_medrxiv_first(
    client: httpx.AsyncClient, sources_transport: FixtureTransport
) -> None:
    project_id = await create_project(client)
    resp = await add(client, project_id, "10.1101/2023.12.14.23299828")
    assert resp.status_code == 201, resp.text
    d = await detail(client, project_id, resp.json()["id"])
    assert d["manifestations"][0]["server_or_venue"] == "medrxiv"
    assert d["resolved_date"]["confidence"] == "verified"
    assert [str(r.url) for r in sources_transport.requests] == [
        "https://api.biorxiv.org/details/medrxiv/10.1101/2023.12.14.23299828"
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
    assert len(d["manifestations"]) == 1
    sources_seen = {(e["event"], e["reporting_source"], e["is_primary"]) for e in d["dates"]}
    assert ("preprint_posted", "biorxiv_api", True) in sources_seen
    assert ("preprint_posted", "crossref", False) in sources_seen
    assert d["resolved_date"]["basis"] == "posted"
    assert db.execute(
        "SELECT count(*) FROM paper_source_links WHERE paper_id = %s", (paper_id,)
    ).fetchone() == (2,)


async def test_api_outage_falls_back_to_crossref_with_an_unconfirmed_date(
    client: httpx.AsyncClient, sources_transport: FixtureTransport
) -> None:
    sources_transport.overrides["api.biorxiv.org"] = lambda r: httpx.Response(502)
    project_id = await create_project(client)
    resp = await add(client, project_id, "10.1101/2022.10.22.513336")
    assert resp.status_code == 201, resp.text
    d = await detail(client, project_id, resp.json()["id"])
    assert d["resolved_date"]["confidence"] == "single_source"
    assert sources_transport.count("api.biorxiv.org") == 4  # retried, then gave up
