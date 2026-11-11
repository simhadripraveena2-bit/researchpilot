"""Enumerations shared by the database, API and services (DATABASE_SCHEMA §2-§7).

Stored as VARCHAR with CHECK constraints (non-native enums), so adding values is a simple
migration and downgrades never have to drop Postgres types.
"""

from __future__ import annotations

from enum import StrEnum


class ExpertiseLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class ProjectGoal(StrEnum):
    LEARN_FIELD = "learn_field"
    REVIEW_LITERATURE = "review_literature"
    FIND_GAP = "find_gap"
    PLAN_EXPERIMENT = "plan_experiment"
    WRITE_PROPOSAL = "write_proposal"
    TRACK_FIELD = "track_field"


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class TutorRetentionPolicy(StrEnum):
    KEEP_UNTIL_DELETED = "keep_until_deleted"
    DELETE_AFTER_DAYS = "delete_after_days"
    DO_NOT_STORE = "do_not_store"


class AuthProvider(StrEnum):
    LOCAL_NONE = "local_none"
    OIDC = "oidc"
    PASSWORD = "password"  # noqa: S105


class TimezoneSource(StrEnum):
    BROWSER = "browser"
    USER = "user"


class ProjectRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class ItemType(StrEnum):
    PAPER = "paper"
    METHOD = "method"
    ARCHITECTURE = "architecture"
    ALGORITHM = "algorithm"
    DATASET = "dataset"
    BENCHMARK = "benchmark"
    METRIC = "metric"
    MODEL = "model"
    TASK = "task"
    CONCEPT = "concept"
    TERM = "term"
    REPOSITORY = "repository"
    GAP = "gap"
    IDEA = "idea"


class ScopeRule(StrEnum):
    """How a node-source row's graph scope is derived (node_source_registry).

    ``self`` is used by ``projects`` (a project node is scoped to itself); it is an addition
    to the documented set and is recorded as an R0 implementation decision.
    """

    GLOBAL = "global"
    SELF = "self"
    OWN_PROJECT_ID = "own_project_id"
    PARENT_PROJECT = "parent_project"


class Workflow(StrEnum):
    DUMMY = "dummy"
    DISCOVERY = "discovery"
    ASSESSMENT = "assessment"
    LEARNING_SETUP = "learning_setup"
    LATEST_SCAN = "latest_scan"
    ANALYSIS = "analysis"
    INVESTIGATION = "investigation"
    EXPERIMENT_DESIGN = "experiment_design"
    REPORT = "report"
    MONITOR = "monitor"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CheckpointStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    MODIFIED = "modified"
    REJECTED = "rejected"


class ClaimKind(StrEnum):
    REPORTED_FINDING = "reported_finding"
    EXTRACTED_OBSERVATION = "extracted_observation"
    AI_INTERPRETATION = "ai_interpretation"
    UNVERIFIED_HYPOTHESIS = "unverified_hypothesis"


class Grounding(StrEnum):
    GROUNDED = "grounded"
    BACKGROUND = "background"


class ClaimStatus(StrEnum):
    ACTIVE = "active"
    HIDDEN_PENDING_REVIEW = "hidden_pending_review"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class ClaimOrigin(StrEnum):
    CARD = "card"
    EXPLANATION = "explanation"
    COMPARISON = "comparison"
    GAP = "gap"
    IDEA = "idea"
    REPORT = "report"
    TUTOR = "tutor"


class EvidenceRelation(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"


class VerificationLevel(StrEnum):
    QUOTE_VERIFIED = "quote_verified"
    DATA_DERIVED = "data_derived"
    METADATA_CONFIRMED = "metadata_confirmed"
    CROSS_CHECKED = "cross_checked"
    UNVERIFIED = "unverified"


class VerificationResult(StrEnum):
    PASS = "pass"  # noqa: S105
    FAIL = "fail"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StageState(StrEnum):
    DONE = "done"
    IN_PROGRESS = "in_progress"
    READY = "ready"
    NOT_READY = "not_ready"


# --- R1 M1a: sources, papers, manifestations and date provenance (DATABASE_SCHEMA §4-§5) ---


class SourceName(StrEnum):
    """An external API we read from (the reporting source of a source record)."""

    ARXIV_API = "arxiv_api"
    ARXIV_ANNOUNCEMENT_FEED = "arxiv_announcement_feed"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    OPENALEX = "openalex"
    CROSSREF = "crossref"
    BIORXIV_API = "biorxiv_api"
    MEDRXIV_API = "medrxiv_api"


class AbstractStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    RESTRICTED = "restricted"


class MetadataLevel(StrEnum):
    STUB = "stub"
    METADATA = "metadata"
    FULL_TEXT = "full_text"


class ManifestationKind(StrEnum):
    PREPRINT = "preprint"
    PUBLISHED = "published"
    OTHER = "other"


class PeerReviewLabel(StrEnum):
    PREPRINT_NOT_PEER_REVIEWED = "preprint_not_peer_reviewed"
    JOURNAL_VERSION = "journal_version"
    UNKNOWN = "unknown"


class DateEvent(StrEnum):
    PREPRINT_SUBMITTED = "preprint_submitted"
    PREPRINT_ANNOUNCED = "preprint_announced"
    PREPRINT_POSTED = "preprint_posted"
    VERSION_SUBMITTED = "version_submitted"
    VERSION_ANNOUNCED = "version_announced"
    VERSION_POSTED = "version_posted"
    ACCEPTED = "accepted"
    PUBLISHED_ONLINE = "published_online"
    ISSUE_PUBLISHED = "issue_published"
    ISSUED = "issued"
    REPORTED_PUBLICATION_DATE = "reported_publication_date"
    INDEX_CREATED = "index_created"
    METADATA_UPDATED = "metadata_updated"
    METADATA_DEPOSITED = "metadata_deposited"
    METADATA_INDEXED = "metadata_indexed"
    FIRST_SEEN_BY_RESEARCHPILOT = "first_seen_by_researchpilot"


class DatePrecision(StrEnum):
    TIMESTAMP = "timestamp"
    DAY = "day"
    MONTH = "month"
    YEAR = "year"


class ReportingSource(StrEnum):
    ARXIV_API = "arxiv_api"
    ARXIV_ANNOUNCEMENT_FEED = "arxiv_announcement_feed"
    BIORXIV_API = "biorxiv_api"
    MEDRXIV_API = "medrxiv_api"
    CROSSREF = "crossref"
    OPENALEX = "openalex"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    RESEARCHPILOT = "researchpilot"


class UpstreamSource(StrEnum):
    ARXIV = "arxiv"
    BIORXIV = "biorxiv"
    MEDRXIV = "medrxiv"
    CROSSREF = "crossref"
    PUBMED = "pubmed"
    PUBLISHER = "publisher"
    DATACITE = "datacite"
    UNKNOWN = "unknown"


class DateConfidence(StrEnum):
    VERIFIED = "verified"
    CORROBORATED = "corroborated"
    SOURCE_AGREEMENT = "source_agreement"
    SINGLE_SOURCE = "single_source"
    CONFLICTING = "conflicting"
    UNCERTAIN = "uncertain"


class FirstPublicBasis(StrEnum):
    ANNOUNCED = "announced"
    POSTED = "posted"
    PUBLISHED_ONLINE = "published_online"
    ISSUE = "issue"
    ISSUED = "issued"
    SUBMISSION_ONLY = "submission_only"


class Inclusion(StrEnum):
    CANDIDATE = "candidate"
    INCLUDED = "included"
    EXCLUDED = "excluded"


class DiscoveredVia(StrEnum):
    SEARCH = "search"
    REFERENCE = "reference"
    CITATION = "citation"
    RECOMMENDATION = "recommendation"
    MANUAL = "manual"
    PROBE = "probe"
    LATEST_SCAN = "latest_scan"
    MONITOR = "monitor"


class ReadingStatus(StrEnum):
    UNREAD = "unread"
    TO_READ = "to_read"
    READING = "reading"
    READ = "read"
    SKIPPED = "skipped"
