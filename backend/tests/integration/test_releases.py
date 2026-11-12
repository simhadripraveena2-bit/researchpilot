"""Release types and date windows through the API, on real recorded records (§4.8.4, D23)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from researchpilot.core.clock import FixedClock
from researchpilot.core.settings import Settings
from tests.fixtures.source_transport import FixtureTransport
from tests.integration.conftest import API, create_project
from tests.integration.test_arxiv_announcements import run_capture

pytestmark = pytest.mark.integration

NOV_12 = datetime(2026, 11, 12, 15, 30, tzinfo=UTC)


async def add(client: httpx.AsyncClient, project_id: str, identifier: str) -> str:
    resp = await client.post(f"{API}/projects/{project_id}/papers", json={"identifier": identifier})
    assert resp.status_code in (200, 201), resp.text
    return str(resp.json()["id"])


async def releases(client: httpx.AsyncClient, project_id: str, **params: Any) -> dict[str, Any]:
    resp = await client.get(f"{API}/projects/{project_id}/releases", params=params)
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


def by_paper(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["paper_id"]: e for e in body["entries"]}


async def test_rolling_week_new_preprint_and_revision_after_announcement_capture(
    app: FastAPI,
    client: httpx.AsyncClient,
    settings: Settings,
    sources_transport: FixtureTransport,
) -> None:
    app.state.clock = FixedClock(NOV_12)
    project_id = await create_project(client)
    new_paper = await add(client, project_id, "2611.13190")  # announced 2026-11-11 (new)
    revised = await add(client, project_id, "2604.22997")  # v2 announced 2026-11-11 (replace)
    await run_capture(settings, sources_transport)

    body = await releases(client, project_id)  # default: rolling 7 days
    assert body["window"]["kind"] == "rolling"
    assert (body["window"]["start"], body["window"]["end"]) == (
        "2026-11-05T15:30:00Z",
        "2026-11-12T15:30:00Z",
    )
    entries = by_paper(body)
    new = entries[new_paper]
    assert (new["release_type"], new["is_new_research"], new["confidence"], new["basis"]) == (
        "new_preprint",
        True,
        "verified",
        "announced",
    )
    assert (new["event"]["event"], new["event"]["local"]["text"]) == (
        "preprint_announced",
        "2026-11-11",
    )
    assert new["peer_review_label"] == "preprint_not_peer_reviewed"
    assert new["publication_type"] == "preprint"
    rev = entries[revised]
    assert (rev["release_type"], rev["is_new_research"], rev["event"]["version"]) == (
        "revised_version",
        False,
        2,
    )
    assert body["new_research"] == 1
    assert body["counts"] == {"new_preprint": 1, "revised_version": 1}


async def test_old_preprint_with_new_journal_version_is_never_new_research(
    client: httpx.AsyncClient,
) -> None:
    """bioRxiv 2022-10-22 -> eLife 2024-06-03: in June 2024 it is a published version of an
    earlier preprint, reported with the preprint's date; in October 2022 it was new."""
    project_id = await create_project(client)
    paper = await add(client, project_id, "10.1101/2022.10.22.513336")
    june = by_paper(
        await releases(client, project_id, **{"from": "2024-06-01", "to": "2024-06-07"})
    )[paper]
    assert (june["release_type"], june["is_new_research"]) == (
        "published_version_of_preprint",
        False,
    )
    assert june["event"]["event"] == "published_online"
    assert june["first_public"]["local"]["text"] == "2022-10-22"
    assert june["notes"] == ["Preprint public since 2022-10-22"]
    october = by_paper(
        await releases(client, project_id, **{"from": "2022-10-20", "to": "2022-10-26"})
    )[paper]
    assert (october["release_type"], october["publication_type"]) == ("new_preprint", "preprint")
    march = by_paper(
        await releases(client, project_id, **{"from": "2023-03-01", "to": "2023-03-07"})
    )[paper]
    assert (march["release_type"], march["event"]["version"]) == ("revised_version", 2)


async def test_corrections_and_retractions_are_notices_not_research(
    client: httpx.AsyncClient,
) -> None:
    project_id = await create_project(client)
    original = await add(client, project_id, "10.1111/psj.70147")
    correction = await add(client, project_id, "10.1111/psj.70162")
    retraction = await add(client, project_id, "10.1080/14767058.2026.2722700")
    assert len({original, correction, retraction}) == 3  # notices never merge into originals
    body = await releases(client, project_id, **{"from": "2026-08-01", "to": "2026-10-31"})
    entries = by_paper(body)
    assert (entries[correction]["release_type"], entries[correction]["publication_type"]) == (
        "correction_notice",
        "correction",
    )
    assert (entries[retraction]["release_type"], entries[retraction]["publication_type"]) == (
        "correction_notice",
        "retraction",
    )
    assert entries[original]["release_type"] == "new_publication"  # online 2026-08-07
    assert body["new_research"] == 1
    matches = (await client.get(f"{API}/projects/{project_id}/papers/{correction}/matches")).json()
    assert {(m["outcome"], m["relation"]) for m in matches if m["other_paper_id"] == original} == {
        ("related_not_same", "erratum_of")
    }


async def test_newly_indexed_old_paper_is_not_new_research(
    app: FastAPI,
    client: httpx.AsyncClient,
) -> None:
    """CVPR 2016 (Crossref: 2016-06 only) first seen now: an older paper newly indexed."""
    project_id = await create_project(client)
    paper = await add(client, project_id, "10.1109/cvpr.2016.90")
    app.state.clock = FixedClock(datetime.now(UTC))  # first seen was just now
    entry = by_paper(await releases(client, project_id))[paper]
    assert (entry["release_type"], entry["is_new_research"]) == ("newly_indexed_older", False)
    assert "first saw it" in entry["notes"][0]


async def test_display_zone_never_changes_membership(
    app: FastAPI, client: httpx.AsyncClient, settings: Settings, sources_transport: FixtureTransport
) -> None:
    app.state.clock = FixedClock(NOV_12)
    project_id = await create_project(client)
    await add(client, project_id, "2611.13190")
    await add(client, project_id, "2604.22997")
    await run_capture(settings, sources_transport)
    results = {}
    for tz in ("UTC", "Europe/Berlin", "America/Los_Angeles", "Asia/Kolkata", "Pacific/Kiritimati"):
        body = await releases(client, project_id, tz=tz)
        results[tz] = sorted((e["paper_id"], e["release_type"]) for e in body["entries"])
        assert body["window"]["timezone"] == tz
    assert len({tuple(v) for v in results.values()}) == 1
    kiritimati = await releases(client, project_id, tz="Pacific/Kiritimati")
    assert kiritimati["window"]["end_local"]["text"] == "2026-11-13 05:30 +14"
    shown = {e["release_type"]: e["event"]["local"] for e in kiritimati["entries"]}
    # The date-only announcement day is the same calendar date in every zone ...
    assert (shown["new_preprint"]["text"], shown["new_preprint"]["date_only"]) == (
        "2026-11-11",
        True,
    )
    # ... while the v2 submission timestamp (2026-11-10 18:10 UTC) is converted.
    assert shown["revised_version"]["text"] == "2026-11-11 08:10 +14"


async def test_user_time_zone_preference_and_paper_detail_display(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.get(f"{API}/me/preferences")).json()["timezone"] == "UTC"
    resp = await client.put(f"{API}/me/preferences", json={"timezone": "Europe/Berlin"})
    assert resp.status_code == 200
    bad = await client.put(f"{API}/me/preferences", json={"timezone": "Mars/Base"})
    assert bad.status_code == 422
    project_id = await create_project(client)
    paper = await add(client, project_id, "2611.13190")
    detail = (await client.get(f"{API}/projects/{project_id}/papers/{paper}")).json()
    submitted = next(d for d in detail["dates"] if d["event"] == "preprint_submitted")
    assert submitted["local"]["text"] == "2026-11-09 21:10 CET"  # 20:10 UTC in Berlin
    la = (
        await client.get(
            f"{API}/projects/{project_id}/papers/{paper}", params={"tz": "America/Los_Angeles"}
        )
    ).json()
    assert (
        next(d for d in la["dates"] if d["event"] == "preprint_submitted")["local"]["text"]
        == "2026-11-09 12:10 PST"
    )
    assert (await releases(client, project_id))["window"]["timezone"] == "Europe/Berlin"


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-11-01"},
        {"from": "2026-11-07", "to": "2026-11-01"},
        {"from": "2026-11-01", "to": "2026-11-07T00:00:00Z"},
        {"days": "0"},
        {"from": "2025-01-01", "to": "2026-12-31"},
        {"tz": "Nowhere/City"},
        {"from": "2026-11-01T00:00:00", "to": "2026-11-02T00:00:00"},
    ],
)
async def test_invalid_windows_are_rejected(
    client: httpx.AsyncClient, params: dict[str, str]
) -> None:
    project_id = await create_project(client)
    resp = await client.get(f"{API}/projects/{project_id}/releases", params=params)
    assert resp.status_code == 422, resp.text


async def test_custom_timestamp_window_and_release_type_filter(
    app: FastAPI,
    client: httpx.AsyncClient,
    settings: Settings,
    sources_transport: FixtureTransport,
) -> None:
    app.state.clock = FixedClock(NOV_12)
    project_id = await create_project(client)
    await add(client, project_id, "2611.13190")
    await add(client, project_id, "2604.22997")
    await run_capture(settings, sources_transport)
    body = await releases(
        client,
        project_id,
        **{
            "from": "2026-11-11T00:00:00+01:00",
            "to": "2026-11-12T00:00:00Z",
            "release_type": "revised_version",
        },
    )
    assert body["window"]["start"] == "2026-11-10T23:00:00Z"
    assert [e["release_type"] for e in body["entries"]] == ["revised_version"]
