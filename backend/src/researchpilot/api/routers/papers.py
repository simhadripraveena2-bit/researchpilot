"""Papers in a project: add by identifier, list, and read with full date provenance."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from researchpilot.api.deps import ProjectScoped, Session
from researchpilot.core.errors import Forbidden
from researchpilot.domain.enums import (
    DateConfidence,
    DateEvent,
    DatePrecision,
    FirstPublicBasis,
    ManifestationKind,
    PeerReviewLabel,
    ProjectRole,
    ReportingSource,
    UpstreamSource,
)
from researchpilot.services.matching import service as matching
from researchpilot.services.papers.service import (
    add_paper_by_identifier,
    get_project_paper,
    list_project_papers,
)

router = APIRouter(tags=["papers"])


class PaperAdd(BaseModel):
    identifier: str = Field(min_length=1, max_length=500, examples=["arXiv:1706.03762"])


class PaperAdded(BaseModel):
    id: uuid.UUID
    added_to_project: bool


class ResolvedDate(BaseModel):
    """The work's first public appearance, or why it is uncertain (D28)."""

    confidence: DateConfidence
    first_public_appearance: datetime | None
    basis: FirstPublicBasis | None
    precision: DatePrecision | None
    event_id: uuid.UUID | None
    manifestation_id: uuid.UUID | None
    candidate_public_date: date | None  # shown only as "unconfirmed"


class PaperSummary(BaseModel):
    id: uuid.UUID
    title: str
    year: int | None
    date_confidence: DateConfidence
    first_public_appearance: datetime | None
    first_public_basis: FirstPublicBasis | None
    candidate_public_date: date | None
    inclusion: str
    reading_status: str
    discovered_via: str


class Manifestation(BaseModel):
    id: uuid.UUID
    kind: ManifestationKind
    server_or_venue: str
    primary_identifier_scheme: str
    primary_identifier_value: str
    peer_review_label: PeerReviewLabel
    url: str | None
    is_open_access: bool | None


class IdentifierOut(BaseModel):
    manifestation_id: uuid.UUID
    scheme: str
    value: str
    version: int | None
    source: str


class DateEventOut(BaseModel):
    id: uuid.UUID
    manifestation_id: uuid.UUID
    event: DateEvent
    value: datetime
    precision: DatePrecision
    version: int | None
    is_primary: bool
    reporting_source: ReportingSource
    upstream_source: UpstreamSource
    upstream_evidence: dict[str, Any] | None
    source_record_id: uuid.UUID | None
    retrieved_at: datetime
    flags: list[str]


class AuthorOut(BaseModel):
    manifestation_id: uuid.UUID
    position: int
    raw_name: str


class PaperDetail(BaseModel):
    id: uuid.UUID
    title: str
    abstract: str | None
    year: int | None
    fields_of_study: list[str]
    resolved_date: ResolvedDate
    manifestations: list[Manifestation]
    identifiers: list[IdentifierOut]
    dates: list[DateEventOut]
    authors: list[AuthorOut]
    inclusion: str
    reading_status: str
    is_saved: bool


@router.post("/projects/{project_id}/papers", status_code=status.HTTP_201_CREATED)
async def add_paper(
    body: PaperAdd, scope: ProjectScoped, session: Session, request: Request, response: Response
) -> PaperAdded:
    """Add a paper by identifier (arXiv ID, arXiv URL or arXiv DOI in this release slice)."""
    if scope.role is ProjectRole.VIEWER:
        raise Forbidden("viewers cannot add papers")
    paper_id, added = await add_paper_by_identifier(
        session, request.app.state.sources, scope.project_id, body.identifier
    )
    if not added:
        response.status_code = status.HTTP_200_OK
    return PaperAdded(id=paper_id, added_to_project=added)


@router.get("/projects/{project_id}/papers")
async def list_papers(scope: ProjectScoped, session: Session) -> list[PaperSummary]:
    rows = await list_project_papers(session, scope.project_id)
    return [PaperSummary.model_validate(r) for r in rows]


@router.get("/projects/{project_id}/papers/{paper_id}")
async def get_paper(paper_id: uuid.UUID, scope: ProjectScoped, session: Session) -> PaperDetail:
    detail = await get_project_paper(session, scope.project_id, paper_id)
    p = detail["paper"]
    return PaperDetail(
        id=p["id"],
        title=p["title"],
        abstract=p["abstract"],
        year=p["year"],
        fields_of_study=p["fields_of_study"],
        resolved_date=ResolvedDate(
            confidence=p["date_confidence"],
            first_public_appearance=p["first_public_appearance"],
            basis=p["first_public_basis"],
            precision=p["first_public_precision"],
            event_id=p["first_public_event_id"],
            manifestation_id=p["first_public_manifestation_id"],
            candidate_public_date=p["candidate_public_date"],
        ),
        manifestations=[Manifestation.model_validate(m) for m in detail["manifestations"]],
        identifiers=[IdentifierOut.model_validate(i) for i in detail["identifiers"]],
        dates=[DateEventOut.model_validate(d) for d in detail["dates"]],
        authors=[AuthorOut.model_validate(a) for a in detail["authors"]],
        inclusion=p["inclusion"],
        reading_status=p["reading_status"],
        is_saved=p["is_saved"],
    )


class MatchOut(BaseModel):
    """A Version Matcher decision about this work and another one (D29)."""

    id: uuid.UUID
    other_paper_id: uuid.UUID
    other_title: str
    other_merged_into: uuid.UUID | None
    outcome: str
    relation: str
    decided_by: str
    user_status: str | None
    confidence: Decimal
    features: dict[str, Any]
    rule_version: str
    merge_id: uuid.UUID | None


class MergeResult(BaseModel):
    paper_id: uuid.UUID


def _editor(scope: ProjectScoped) -> None:
    if scope.role is ProjectRole.VIEWER:
        raise Forbidden("viewers cannot change matches")


@router.get("/projects/{project_id}/papers/{paper_id}/matches")
async def list_matches(
    paper_id: uuid.UUID, scope: ProjectScoped, session: Session
) -> list[MatchOut]:
    """Possible matches, merges and related works for this paper, with their evidence."""
    rows = await matching.list_matches(session, scope.project_id, paper_id)
    return [
        MatchOut(
            id=r["id"],
            other_paper_id=r["other_id"],
            other_title=r["other_title"],
            other_merged_into=r["other_merged_into"],
            outcome=r["outcome"],
            relation=r["relation"],
            decided_by=r["decided_by"],
            user_status=r["user_status"],
            confidence=r["confidence"],
            features=r["features"],
            rule_version=r["rule_version"],
            merge_id=r["merge_id"],
        )
        for r in rows
    ]


@router.post("/projects/{project_id}/matches/{decision_id}/confirm")
async def confirm_match(
    decision_id: uuid.UUID, scope: ProjectScoped, session: Session
) -> MergeResult:
    """The user confirms a possible match: the works are merged (reversible)."""
    _editor(scope)
    return MergeResult(paper_id=await matching.confirm(session, scope.project_id, decision_id))


@router.post(
    "/projects/{project_id}/matches/{decision_id}/reject", status_code=status.HTTP_204_NO_CONTENT
)
async def reject_match(decision_id: uuid.UUID, scope: ProjectScoped, session: Session) -> None:
    """The user says these are different works; automatic matching never proposes it again."""
    _editor(scope)
    await matching.reject(session, scope.project_id, decision_id)


@router.post(
    "/projects/{project_id}/merges/{merge_id}/split", status_code=status.HTTP_204_NO_CONTENT
)
async def split_merge(merge_id: uuid.UUID, scope: ProjectScoped, session: Session) -> None:
    """Undo a merge exactly; the pair is then remembered as rejected."""
    _editor(scope)
    await matching.split(session, scope.project_id, merge_id)
