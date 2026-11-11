"""Version Matcher on real recorded records (D29; R1-44, R1-45, R1-46).

* decisive links merge (arXiv author DOI, bioRxiv/medRxiv published, Crossref relations);
* similar titles without identifier links are at most possible matches, linked not merged;
* adversarial look-alikes (Part I/II, authorless records, comment/reply) never merge;
* a merge keeps every source record, identifier and date claim per manifestation, and a
  split restores both works exactly; user decisions are sticky.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import psycopg
import pytest

from tests.integration.conftest import API, create_project

pytestmark = pytest.mark.integration


async def add(client: httpx.AsyncClient, project_id: str, identifier: str) -> str:
    resp = await client.post(f"{API}/projects/{project_id}/papers", json={"identifier": identifier})
    assert resp.status_code in (200, 201), resp.text
    return str(resp.json()["id"])


async def matches(
    client: httpx.AsyncClient, project_id: str, paper_id: str
) -> list[dict[str, Any]]:
    resp = await client.get(f"{API}/projects/{project_id}/papers/{paper_id}/matches")
    assert resp.status_code == 200, resp.text
    return list(resp.json())


def paper_count(db: psycopg.Connection) -> int:
    row = db.execute("SELECT count(*) FROM papers WHERE merged_into_id IS NULL").fetchone()
    return int(row[0]) if row else 0


def snapshot(db: psycopg.Connection, paper_id: str) -> dict[str, frozenset[tuple[Any, ...]]]:
    """Everything that belongs to a work's manifestations, keyed by manifestation."""
    queries = {
        "manifestations": "SELECT id, kind, primary_identifier_value FROM paper_manifestations "
        "WHERE paper_id = %s",
        "identifiers": "SELECT manifestation_id, scheme, value, version FROM paper_identifiers "
        "WHERE paper_id = %s",
        "dates": "SELECT id, manifestation_id, event, value, precision, version, is_primary, "
        "reporting_source, upstream_source, source_record_id FROM paper_dates WHERE paper_id = %s",
        "versions": "SELECT manifestation_id, version, submitted_at FROM paper_versions "
        "WHERE paper_id = %s",
        "authors": "SELECT manifestation_id, position, raw_name FROM paper_authors "
        "WHERE paper_id = %s",
        "links": "SELECT manifestation_id, link_type, target_value, source FROM "
        "paper_version_links WHERE paper_id = %s",
        "source_links": "SELECT manifestation_id, source_record_id FROM paper_source_links "
        "WHERE paper_id = %s",
    }
    return {
        k: frozenset(tuple(r) for r in db.execute(q, (paper_id,)).fetchall())
        for k, q in queries.items()
    }


async def test_arxiv_author_doi_merges_and_unlinked_versions_stay_possible(
    client: httpx.AsyncClient, db: psycopg.Connection
) -> None:
    """Maldacena: arXiv's DOI points to the IJTP reprint (decisive -> merged); the ATMP
    original and the AIP proceedings share title and author but have no identifier link:
    possible matches, linked and visible, not merged."""
    project_id = await create_project(client)
    work = await add(client, project_id, "hep-th/9711200")
    atmp = await add(client, project_id, "10.4310/atmp.1998.v2.n2.a1")
    aip = await add(client, project_id, "10.1063/1.59653")
    assert len({work, atmp, aip}) == 3
    assert paper_count(db) == 3

    decisions = await matches(client, project_id, work)
    by_other = {d["other_title"]: d for d in decisions}
    merged = next(d for d in decisions if d["outcome"] == "auto_match")
    assert merged["merge_id"] is not None
    assert merged["features"]["explicit_relation"][0]["source"] == "arxiv_api"
    possible = [d for d in decisions if d["outcome"] == "possible_match"]
    assert {d["other_paper_id"] for d in possible} == {atmp, aip}
    assert all(d["user_status"] == "pending" and d["merge_id"] is None for d in possible)
    assert all(d["features"]["title_sim"] >= 0.9 for d in possible)
    assert by_other  # titles are returned for display


async def test_confirm_merges_then_split_restores_exactly_and_stays_rejected(
    client: httpx.AsyncClient, db: psycopg.Connection, app: object
) -> None:
    project_id = await create_project(client)
    other_project = await create_project(client)
    work = await add(client, project_id, "hep-th/9711200")
    atmp = await add(client, project_id, "10.4310/atmp.1998.v2.n2.a1")
    await add(client, other_project, "10.4310/atmp.1998.v2.n2.a1")
    before = {work: snapshot(db, work), atmp: snapshot(db, atmp)}
    records_before = db.execute("SELECT count(*) FROM source_records").fetchone()

    decision = next(
        d for d in await matches(client, project_id, work) if d["other_paper_id"] == atmp
    )
    confirmed = await client.post(f"{API}/projects/{project_id}/matches/{decision['id']}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    survivor = confirmed.json()["paper_id"]
    assert survivor == work  # the older work survives
    after_merge = snapshot(db, work)
    for key in before[work]:
        assert after_merge[key] == before[work][key] | before[atmp][key]  # nothing lost
    assert snapshot(db, atmp)["manifestations"] == frozenset()
    # Both projects now list the surviving work.
    for pid in (project_id, other_project):
        listed = (await client.get(f"{API}/projects/{pid}/papers")).json()
        assert work in {p["id"] for p in listed} and atmp not in {p["id"] for p in listed}

    merge_id = next(
        d["merge_id"] for d in await matches(client, project_id, work) if d["id"] == decision["id"]
    )
    split = await client.post(f"{API}/projects/{project_id}/merges/{merge_id}/split")
    assert split.status_code == 204, split.text
    assert snapshot(db, work) == before[work]
    assert snapshot(db, atmp) == before[atmp]
    assert db.execute("SELECT count(*) FROM source_records").fetchone() == records_before
    listed = {p["id"] for p in (await client.get(f"{API}/projects/{other_project}/papers")).json()}
    assert listed == {atmp}

    # The split is a sticky rejection: running the matcher again never merges them.
    row = db.execute(
        "SELECT decided_by, user_status FROM paper_match_decisions WHERE id = %s", (decision["id"],)
    ).fetchone()
    assert row == ("user", "rejected")
    from researchpilot.services.matching.store import match_work

    async with app.state.sessions() as session, session.begin():  # type: ignore[attr-defined]
        assert str(await match_work(session, uuid.UUID(atmp))) == atmp
    assert db.execute("SELECT merged_into_id FROM papers WHERE id = %s", (atmp,)).fetchone() == (
        None,
    )
    assert db.execute(
        "SELECT decided_by, user_status FROM paper_match_decisions WHERE id = %s", (decision["id"],)
    ).fetchone() == ("user", "rejected")


async def test_system_cannot_override_a_user_decision(
    client: httpx.AsyncClient, db: psycopg.Connection
) -> None:
    project_id = await create_project(client)
    work = await add(client, project_id, "hep-th/9711200")
    await add(client, project_id, "10.1063/1.59653")
    decision = next(
        d for d in await matches(client, project_id, work) if d["outcome"] == "possible_match"
    )
    resp = await client.post(f"{API}/projects/{project_id}/matches/{decision['id']}/reject")
    assert resp.status_code == 204
    with pytest.raises(psycopg.errors.CheckViolation, match="cannot be overridden"):
        db.execute(
            "UPDATE paper_match_decisions SET decided_by = 'system' WHERE id = %s",
            (decision["id"],),
        )
    db.rollback()
    with pytest.raises(psycopg.errors.CheckViolation, match="already decided"):
        db.execute(
            "INSERT INTO paper_match_decisions (id, paper_a, paper_b, relation, outcome, "
            "decided_by, confidence, features, rule_version) SELECT gen_random_uuid(), paper_a, "
            "paper_b, 'same_work', 'auto_match', 'system', 1, '{}', 'd29-v2' "
            "FROM paper_match_decisions WHERE id = %s",
            (decision["id"],),
        )
    db.rollback()


async def test_part_one_and_part_two_are_never_merged(
    client: httpx.AsyncClient, db: psycopg.Connection
) -> None:
    project_id = await create_project(client)
    part1 = await add(client, project_id, "10.1016/0167-9473(95)00032-1")
    part2 = await add(client, project_id, "10.1016/0167-9473(95)00033-x")
    assert part1 != part2 and paper_count(db) == 2
    [decision] = await matches(client, project_id, part2)
    assert decision["outcome"] == "no_match"
    assert "part_number_differs" in decision["features"]["contradicting"]
    assert decision["features"]["title_sim"] > 0.95


async def test_identical_title_authorless_record_is_never_merged(
    client: httpx.AsyncClient, db: psycopg.Connection
) -> None:
    project_id = await create_project(client)
    primer = await add(client, project_id, "10.1038/s43586-024-00294-7")
    summary = await add(client, project_id, "10.1038/s43586-024-00304-8")
    assert primer != summary
    [decision] = await matches(client, project_id, summary)
    assert (decision["outcome"], decision["features"]["title_sim"]) == ("no_match", 1.0)
    assert decision["features"]["author_overlap"] is None


async def test_reply_and_comment_are_related_not_same(client: httpx.AsyncClient) -> None:
    project_id = await create_project(client)
    comment = await add(client, project_id, "10.3390/insects17070712")
    reply = await add(client, project_id, "10.3390/insects17070713")
    assert comment != reply
    [decision] = await matches(client, project_id, reply)
    assert (decision["outcome"], decision["relation"]) == (
        "related_not_same",
        "comment_or_reply_of",
    )
    resp = await client.post(f"{API}/projects/{project_id}/matches/{decision['id']}/confirm")
    assert resp.status_code == 422  # related works can never be merged


async def test_resnet_arxiv_and_cvpr_are_only_possible_without_more_evidence(
    client: httpx.AsyncClient,
) -> None:
    """Same title and authors, no identifier link (arXiv has no DOI field): possible match
    until Semantic Scholar/OpenAlex evidence (strong) is available."""
    project_id = await create_project(client)
    arxiv = await add(client, project_id, "1512.03385")
    cvpr = await add(client, project_id, "10.1109/cvpr.2016.90")
    assert arxiv != cvpr
    [decision] = await matches(client, project_id, cvpr)
    assert decision["outcome"] == "possible_match"
    assert decision["features"]["first_author_match"] is True


async def test_preprint_journal_pair_merges_in_either_order(
    client: httpx.AsyncClient, db: psycopg.Connection
) -> None:
    """Journal first (has-preprint followed to bioRxiv) or preprint first (published
    followed to eLife): one work, distinct manifestations, preprint date first."""
    project_id = await create_project(client)
    work = await add(client, project_id, "10.7554/elife.87434")
    same = await add(client, project_id, "10.1101/2022.10.22.513336")
    assert work == same and paper_count(db) == 1
    kinds = db.execute(
        "SELECT kind, server_or_venue FROM paper_manifestations WHERE paper_id = %s ORDER BY kind",
        (work,),
    ).fetchall()
    assert ("preprint", "biorxiv") in kinds and ("published", "eLife") in kinds
    resolved = db.execute(
        "SELECT first_public_basis, first_public_appearance::date::text FROM papers WHERE id = %s",
        (work,),
    ).fetchone()
    assert resolved == ("posted", "2022-10-22")


async def test_semantic_scholar_strong_evidence_merges_resnet_versions(
    authenticated_client: httpx.AsyncClient, db: psycopg.Connection
) -> None:
    """With a key, Semantic Scholar's real record for the CVPR DOI lists the arXiv ID too
    (strong evidence); with matching title and authors the arXiv preprint and the CVPR paper
    become one work. Recorded authenticated response (2026-11-11)."""
    client = authenticated_client
    project_id = await create_project(client)
    cvpr = await add(client, project_id, "10.1109/cvpr.2016.90")
    resp = await client.post(
        f"{API}/projects/{project_id}/papers", json={"identifier": "1512.03385"}
    )
    assert resp.json()["coverage"]["semantic_scholar"] == "ok"
    assert resp.json()["id"] == cvpr
    decision = next(
        d for d in await matches(client, project_id, cvpr) if d["outcome"] == "auto_match"
    )
    assert decision["features"]["strong_links"][0]["source"] == "semantic_scholar"
    assert decision["features"]["explicit_relation"] == []
    kinds = {
        r[0]
        for r in db.execute(
            "SELECT kind FROM paper_manifestations WHERE paper_id = %s", (cvpr,)
        ).fetchall()
    }
    assert kinds == {"preprint", "published"}


async def test_add_by_openalex_id_resolves_to_the_system_of_record(
    client: httpx.AsyncClient, db: psycopg.Connection
) -> None:
    project_id = await create_project(client)
    paper_id = await add(client, project_id, "https://openalex.org/W2194775991")
    assert db.execute(
        "SELECT scheme, value FROM paper_identifiers WHERE paper_id = %s ORDER BY scheme",
        (paper_id,),
    ).fetchall() == [("doi", "10.1109/cvpr.2016.90"), ("openalex", "W2194775991")]
    assert db.execute(
        "SELECT DISTINCT reporting_source FROM paper_dates WHERE paper_id = %s AND is_primary",
        (paper_id,),
    ).fetchall() == [("crossref",)]
