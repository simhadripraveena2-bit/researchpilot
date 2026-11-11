"""Crossref: DOI -> published or preprint manifestation with every date event kept."""

from __future__ import annotations

import httpx
import pytest

from tests.fixtures.source_transport import FixtureTransport
from tests.integration.conftest import API, create_project

pytestmark = pytest.mark.integration


async def add_and_get(client: httpx.AsyncClient, identifier: str) -> dict:  # type: ignore[type-arg]
    project_id = await create_project(client)
    resp = await client.post(f"{API}/projects/{project_id}/papers", json={"identifier": identifier})
    assert resp.status_code == 201, resp.text
    detail = await client.get(f"{API}/projects/{project_id}/papers/{resp.json()['id']}")
    return dict(detail.json())


async def test_journal_article_is_a_published_manifestation_with_verified_date(
    client: httpx.AsyncClient,
) -> None:
    d = await add_and_get(client, "https://doi.org/10.7554/eLife.87434")
    [m] = d["manifestations"]
    assert (m["kind"], m["server_or_venue"], m["peer_review_label"]) == (
        "published",
        "eLife",
        "journal_version",
    )
    events = {e["event"]: e for e in d["dates"]}
    assert events["published_online"]["is_primary"] is True
    assert events["published_online"]["upstream_evidence"] == {
        "field": "published-online",
        "date_parts": [2024, 6, 3],
    }
    assert {"issued", "index_created", "metadata_deposited", "metadata_indexed"} <= set(events)
    for metadata in ("metadata_deposited", "metadata_indexed", "index_created"):
        assert d["resolved_date"]["event_id"] != events[metadata]["id"]
    r = d["resolved_date"]
    assert (r["confidence"], r["basis"]) == ("verified", "published_online")
    assert r["first_public_appearance"].startswith("2024-06-03")


async def test_biorxiv_doi_via_crossref_alone_is_unconfirmed(
    client: httpx.AsyncClient, sources_transport: FixtureTransport
) -> None:
    """If the preprint servers don't return the record, Crossref is used; it is not the
    system of record for bioRxiv dates (secondary, upstream bioRxiv), so the date stays
    unconfirmed."""
    sources_transport.overrides["api.biorxiv.org"] = lambda r: httpx.Response(
        200, json={"messages": [{"status": "no posts found"}], "collection": []}
    )
    d = await add_and_get(client, "doi:10.1101/2022.10.22.513336")
    [m] = d["manifestations"]
    assert (m["kind"], m["server_or_venue"], m["peer_review_label"]) == (
        "preprint",
        "biorxiv",
        "preprint_not_peer_reviewed",
    )
    posted = next(e for e in d["dates"] if e["event"] == "preprint_posted")
    assert (posted["is_primary"], posted["reporting_source"], posted["upstream_source"]) == (
        False,
        "crossref",
        "biorxiv",
    )
    assert not any(e["event"] == "accepted" for e in d["dates"])  # not a journal acceptance
    assert d["resolved_date"]["confidence"] == "single_source"
    assert d["resolved_date"]["candidate_public_date"] == "2022-10-22"


async def test_month_precision_journal_date_is_uncertain(client: httpx.AsyncClient) -> None:
    d = await add_and_get(client, "10.1023/A:1026654312961")
    issued = next(e for e in d["dates"] if e["event"] == "issued")
    assert issued["precision"] == "month"
    assert d["resolved_date"]["confidence"] == "uncertain"
    assert d["resolved_date"]["first_public_appearance"] is None


async def test_unknown_doi_is_not_found(client: httpx.AsyncClient) -> None:
    project_id = await create_project(client)
    resp = await client.post(
        f"{API}/projects/{project_id}/papers", json={"identifier": "10.1234/rp-does-not-exist"}
    )
    assert (resp.status_code, resp.json()["code"]) == (404, "source_not_found")


async def test_crossref_server_errors_are_retried_then_reported(
    client: httpx.AsyncClient, sources_transport: object
) -> None:
    calls: list[int] = []

    def failing(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, headers={"Retry-After": "0"})

    sources_transport.overrides["api.crossref.org"] = failing  # type: ignore[attr-defined]
    project_id = await create_project(client)
    resp = await client.post(
        f"{API}/projects/{project_id}/papers", json={"identifier": "10.7554/elife.87434"}
    )
    assert (resp.status_code, resp.json()["code"]) == (503, "source_unavailable")
    assert len(calls) == 4  # max_attempts
