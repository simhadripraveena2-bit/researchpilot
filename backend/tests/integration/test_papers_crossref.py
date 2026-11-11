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


async def test_journal_article_is_a_published_manifestation_with_every_date_kept(
    client: httpx.AsyncClient,
) -> None:
    """eLife journal DOI: a published manifestation with every Crossref date as its own
    event. Its has-preprint link brings in the bioRxiv preprint, so the work's first public
    appearance is the earlier, verified preprint posting - not the journal date."""
    d = await add_and_get(client, "https://doi.org/10.7554/eLife.87434")
    elife = next(
        m for m in d["manifestations"] if m["primary_identifier_value"] == "10.7554/elife.87434"
    )
    assert (elife["kind"], elife["server_or_venue"], elife["peer_review_label"]) == (
        "published",
        "eLife",
        "journal_version",
    )
    events = {e["event"]: e for e in d["dates"] if e["manifestation_id"] == elife["id"]}
    assert events["published_online"]["is_primary"] is True
    assert events["published_online"]["upstream_evidence"] == {
        "field": "published-online",
        "date_parts": [2024, 6, 3],
    }
    assert {"issued", "index_created", "metadata_deposited", "metadata_indexed"} <= set(events)
    r = d["resolved_date"]
    assert (r["confidence"], r["basis"]) == ("verified", "posted")
    assert r["first_public_appearance"].startswith("2022-10-22")
    assert r["manifestation_id"] != elife["id"]


async def test_journal_only_paper_is_verified_from_crossref(client: httpx.AsyncClient) -> None:
    d = await add_and_get(client, "10.1109/cvpr.2016.90")
    [m] = d["manifestations"]
    assert (m["kind"], m["server_or_venue"]) == (
        "published",
        "2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)",
    )
    # Only "2016-06" is deposited: no day-precision date can be confirmed.
    assert d["resolved_date"]["confidence"] == "uncertain"


async def test_biorxiv_doi_via_crossref_alone_is_unconfirmed(
    client: httpx.AsyncClient, sources_transport: FixtureTransport
) -> None:
    """If the preprint servers don't return the record, Crossref is used; it is not the
    system of record for bioRxiv dates (secondary, upstream bioRxiv). The matched eLife
    version is primary but later, so the work's date is conflicting, not the journal's."""
    sources_transport.overrides["api.biorxiv.org"] = lambda r: httpx.Response(
        200, json={"messages": [{"status": "no posts found"}], "collection": []}
    )
    d = await add_and_get(client, "doi:10.1101/2022.10.22.513336")
    [m] = [m for m in d["manifestations"] if m["kind"] == "preprint"]
    assert (m["server_or_venue"], m["peer_review_label"]) == (
        "biorxiv",
        "preprint_not_peer_reviewed",
    )
    preprint_events = [e for e in d["dates"] if e["manifestation_id"] == m["id"]]
    posted = next(e for e in preprint_events if e["event"] == "preprint_posted")
    assert (posted["is_primary"], posted["reporting_source"], posted["upstream_source"]) == (
        False,
        "crossref",
        "biorxiv",
    )
    assert not any(e["event"] == "accepted" for e in preprint_events)  # not an acceptance
    r = d["resolved_date"]
    assert (r["confidence"], r["candidate_public_date"]) == ("conflicting", "2022-10-22")


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
