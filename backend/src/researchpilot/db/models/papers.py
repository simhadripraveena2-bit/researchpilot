"""Works, manifestations, identifiers and date events (DATABASE_SCHEMA §5, ARCHITECTURE §4.8).

A **work** (``papers``) has one or more **manifestations** (arXiv preprint, bioRxiv/medRxiv
preprint, journal version). Identifiers, versions and date events belong to a manifestation,
so preprint and published versions stay distinct after they are matched to one work.
Date events are never overwritten or deleted by matching.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from researchpilot.db.base import Base, created_at, enum_type, row_version, updated_at, uuid_pk
from researchpilot.domain.enums import (
    AbstractStatus,
    DateConfidence,
    DateEvent,
    DatePrecision,
    DiscoveredVia,
    FirstPublicBasis,
    Inclusion,
    ManifestationKind,
    MetadataLevel,
    PeerReviewLabel,
    ReadingStatus,
    ReportingSource,
    SourceName,
    UpstreamSource,
)
from researchpilot.domain.identifiers import IdentifierScheme

_SOURCE_RECORD_FK = "source_records.id"


class Paper(Base):
    """The work. Its id is the research item id (supertype)."""

    __tablename__ = "papers"
    __table_args__ = (
        sa.Index(
            "ix_papers_normalized_title_trgm",
            "normalized_title",
            postgresql_using="gin",
            postgresql_ops={"normalized_title": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("research_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    normalized_title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    abstract: Mapped[str | None] = mapped_column(sa.Text)
    abstract_status: Mapped[AbstractStatus] = mapped_column(
        enum_type(AbstractStatus, "abstract_status"),
        nullable=False,
        server_default=AbstractStatus.UNAVAILABLE.value,
    )
    abstract_manifestation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("paper_manifestations.id", ondelete="SET NULL", use_alter=True),
    )
    year: Mapped[int | None] = mapped_column(sa.Integer, index=True)
    venue: Mapped[str | None] = mapped_column(sa.Text)
    publication_type: Mapped[str | None] = mapped_column(sa.Text)
    is_survey: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false(), nullable=False)
    is_open_access: Mapped[bool | None] = mapped_column(sa.Boolean)
    language: Mapped[str | None] = mapped_column(sa.Text)
    fields_of_study: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), server_default=sa.text("'{}'::text[]"), nullable=False
    )
    citation_counts: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
    )
    field_sources: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
    )
    metadata_level: Mapped[MetadataLevel] = mapped_column(
        enum_type(MetadataLevel, "metadata_level"),
        nullable=False,
        server_default=MetadataLevel.METADATA.value,
    )
    # Resolved dates (Date Resolver, D28 revised). first_public_* is set only for verified or
    # corroborated confidence; otherwise only candidate_public_date ("unconfirmed").
    first_public_appearance: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), index=True
    )
    first_public_basis: Mapped[FirstPublicBasis | None] = mapped_column(
        enum_type(FirstPublicBasis, "first_public_basis")
    )
    first_public_precision: Mapped[DatePrecision | None] = mapped_column(
        enum_type(DatePrecision, "date_precision")
    )
    first_public_manifestation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("paper_manifestations.id", ondelete="SET NULL", use_alter=True),
    )
    first_public_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("paper_dates.id", ondelete="SET NULL", use_alter=True)
    )
    candidate_public_date: Mapped[date | None] = mapped_column(sa.Date)
    date_confidence: Mapped[DateConfidence] = mapped_column(
        enum_type(DateConfidence, "date_confidence"),
        nullable=False,
        server_default=DateConfidence.UNCERTAIN.value,
    )
    # Set while this work is merged into another (D29); cleared again by a split.
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("papers.id", ondelete="SET NULL"), index=True
    )
    row_version: Mapped[int] = row_version()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class PaperManifestation(Base):
    """One version of a work (preprint, published, other). Also the single source of
    HAS_VERSION (via ``paper_id``); global by construction (no scope column)."""

    __tablename__ = "paper_manifestations"
    __table_args__ = (
        sa.UniqueConstraint("primary_identifier_scheme", "primary_identifier_value"),
        sa.Index("ix_paper_manifestations_paper_id_kind", "paper_id", "kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ManifestationKind] = mapped_column(
        enum_type(ManifestationKind, "manifestation_kind"), nullable=False
    )
    server_or_venue: Mapped[str] = mapped_column(sa.Text, nullable=False)
    primary_identifier_scheme: Mapped[IdentifierScheme] = mapped_column(
        enum_type(IdentifierScheme, "identifier_scheme"), nullable=False
    )
    primary_identifier_value: Mapped[str] = mapped_column(sa.Text, nullable=False)
    peer_review_label: Mapped[PeerReviewLabel] = mapped_column(
        enum_type(PeerReviewLabel, "peer_review_label"), nullable=False
    )
    url: Mapped[str | None] = mapped_column(sa.Text)
    license: Mapped[str | None] = mapped_column(sa.Text)
    is_open_access: Mapped[bool | None] = mapped_column(sa.Boolean)
    created_from_source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey(_SOURCE_RECORD_FK, ondelete="SET NULL")
    )
    row_version: Mapped[int] = row_version()
    created_at: Mapped[datetime] = created_at()


class PaperIdentifier(Base):
    """Identifier of a manifestation. ``UNIQUE(scheme, value)`` is the deduplication guard."""

    __tablename__ = "paper_identifiers"
    __table_args__ = (sa.UniqueConstraint("scheme", "value"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    manifestation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("paper_manifestations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scheme: Mapped[IdentifierScheme] = mapped_column(
        enum_type(IdentifierScheme, "identifier_scheme"), nullable=False
    )
    value: Mapped[str] = mapped_column(sa.Text, nullable=False)
    version: Mapped[int | None] = mapped_column(sa.Integer)
    source: Mapped[SourceName] = mapped_column(enum_type(SourceName, "source_name"), nullable=False)
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey(_SOURCE_RECORD_FK, ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()


class PaperDate(Base):
    """One date event of one manifestation, with its provenance. Never overwritten."""

    __tablename__ = "paper_dates"
    __table_args__ = (
        sa.Index("ix_paper_dates_paper_id_event", "paper_id", "event"),
        # Idempotent ingestion: the same claim from the same source is stored once.
        sa.Index(
            "uq_paper_dates_claim",
            "manifestation_id",
            "event",
            sa.text("coalesce(version, 0)"),
            "reporting_source",
            "value",
            "precision",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    manifestation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("paper_manifestations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event: Mapped[DateEvent] = mapped_column(enum_type(DateEvent, "date_event"), nullable=False)
    value: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    precision: Mapped[DatePrecision] = mapped_column(
        enum_type(DatePrecision, "date_precision"), nullable=False
    )
    version: Mapped[int | None] = mapped_column(sa.Integer)
    is_primary: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    reporting_source: Mapped[ReportingSource] = mapped_column(
        enum_type(ReportingSource, "reporting_source"), nullable=False
    )
    upstream_source: Mapped[UpstreamSource] = mapped_column(
        enum_type(UpstreamSource, "upstream_source"),
        nullable=False,
        server_default=UpstreamSource.UNKNOWN.value,
    )
    upstream_evidence: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey(_SOURCE_RECORD_FK, ondelete="SET NULL")
    )
    retrieved_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    flags: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), server_default=sa.text("'{}'::text[]"), nullable=False
    )


class PaperVersion(Base):
    """Preprint versions (arXiv v1, v2, ...) of one manifestation."""

    __tablename__ = "paper_versions"

    manifestation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("paper_manifestations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    source: Mapped[SourceName] = mapped_column(enum_type(SourceName, "source_name"), nullable=False)
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey(_SOURCE_RECORD_FK, ondelete="SET NULL")
    )


class PaperSourceLink(Base):
    __tablename__ = "paper_source_links"

    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey(_SOURCE_RECORD_FK, ondelete="CASCADE"),
        primary_key=True,
    )
    manifestation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("paper_manifestations.id", ondelete="CASCADE")
    )


class PaperAuthor(Base):
    """Author list as reported by a manifestation's source. ``author_id`` stays empty until
    author resolution (S2/OpenAlex author IDs, ORCID) links it to an ``authors`` row."""

    __tablename__ = "paper_authors"

    manifestation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("paper_manifestations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    raw_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    raw_affiliations: Mapped[list[object]] = mapped_column(
        JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False
    )


class ProjectItem(Base):
    """Project membership, inclusion and reading status of an item."""

    __tablename__ = "project_items"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("research_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    inclusion: Mapped[Inclusion] = mapped_column(
        enum_type(Inclusion, "inclusion"), nullable=False, server_default=Inclusion.CANDIDATE.value
    )
    exclusion_reason: Mapped[str | None] = mapped_column(sa.Text)
    dismissed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    dismiss_reason: Mapped[str | None] = mapped_column(sa.Text)
    discovered_via: Mapped[DiscoveredVia] = mapped_column(
        enum_type(DiscoveredVia, "discovered_via"), nullable=False
    )
    discovered_in_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("research_runs.id", ondelete="SET NULL")
    )
    discovered_from_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("research_items.id", ondelete="SET NULL")
    )
    reading_status: Mapped[ReadingStatus] = mapped_column(
        enum_type(ReadingStatus, "reading_status"),
        nullable=False,
        server_default=ReadingStatus.UNREAD.value,
    )
    last_section_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    is_saved: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false(), nullable=False)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), server_default=sa.text("'{}'::text[]"), nullable=False
    )
    first_seen_at: Mapped[datetime] = created_at()
