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


class MatchRelation(StrEnum):
    SAME_WORK = "same_work"
    PREPRINT_OF = "preprint_of"
    PUBLISHED_VERSION_OF = "published_version_of"
    EXTENDED_VERSION_OF = "extended_version_of"
    ERRATUM_OF = "erratum_of"
    COMMENT_OR_REPLY_OF = "comment_or_reply_of"
    UNRELATED = "unrelated"


class MatchOutcome(StrEnum):
    AUTO_MATCH = "auto_match"
    POSSIBLE_MATCH = "possible_match"
    RELATED_NOT_SAME = "related_not_same"
    NO_MATCH = "no_match"


class DecidedBy(StrEnum):
    SYSTEM = "system"
    USER = "user"


class UserMatchStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class MergeMethod(StrEnum):
    IDENTIFIER = "identifier"
    VERSION_RELATION = "version_relation"
    EVIDENCE_RULES = "evidence_rules"
    MANUAL = "manual"


class PublicationType(StrEnum):
    """What a manifestation is (explicit; independent of when it appeared)."""

    PREPRINT = "preprint"
    JOURNAL_ARTICLE = "journal_article"
    CONFERENCE_PAPER = "conference_paper"
    BOOK_CHAPTER = "book_chapter"
    BOOK = "book"
    DISSERTATION = "dissertation"
    REPORT = "report"
    DATASET = "dataset"
    # Notices about another work (Crossref ``update-to``); never research of their own.
    CORRECTION = "correction"
    RETRACTION = "retraction"
    EXPRESSION_OF_CONCERN = "expression_of_concern"
    OTHER = "other"


NOTICE_TYPES = frozenset(
    {PublicationType.CORRECTION, PublicationType.RETRACTION, PublicationType.EXPRESSION_OF_CONCERN}
)


class ReleaseType(StrEnum):
    """Why a work appears in a date window (ARCHITECTURE §4.8.4)."""

    NEW_PREPRINT = "new_preprint"
    NEW_PUBLICATION = "new_publication"
    PUBLISHED_VERSION_OF_PREPRINT = "published_version_of_preprint"
    REVISED_VERSION = "revised_version"
    CORRECTION_NOTICE = "correction_notice"
    NEWLY_INDEXED_OLDER = "newly_indexed_older"
    DATE_UNCERTAIN = "date_uncertain"


NEW_RESEARCH = frozenset({ReleaseType.NEW_PREPRINT, ReleaseType.NEW_PUBLICATION})


class ObjectiveSource(StrEnum):
    PLANNER = "planner"
    USER_EDIT = "user_edit"
    FEEDBACK_SUGGESTION = "feedback_suggestion"


class RelationClass(StrEnum):
    RESEARCH = "research"
    STRUCTURAL = "structural"


class ScopePolicy(StrEnum):
    GLOBAL_ONLY = "global_only"
    PROJECT_ONLY = "project_only"
    PROJECT_OR_GLOBAL = "project_or_global"


class OnParentDelete(StrEnum):
    CASCADE_CHILD = "cascade_child"
    DETACH = "detach"


class Assertion(StrEnum):
    """How a relationship is known (ARCHITECTURE §12.5)."""

    SOURCE_METADATA = "source_metadata"
    AUTHOR_REPORTED = "author_reported"
    EXTRACTED = "extracted"
    COMPUTED = "computed"
    INFERRED = "inferred"
    HYPOTHESIZED = "hypothesized"
    USER_ASSERTED = "user_asserted"
    USER_CONFIRMED = "user_confirmed"
    REJECTED = "rejected"
    STRUCTURAL = "structural"


# A global (null-scope) relationship may only come from global inputs (§12.4.2a).
GLOBAL_ASSERTIONS = frozenset(
    {
        Assertion.SOURCE_METADATA,
        Assertion.AUTHOR_REPORTED,
        Assertion.EXTRACTED,
        Assertion.COMPUTED,
        Assertion.INFERRED,
    }
)
USER_ASSERTIONS = frozenset({Assertion.USER_ASSERTED, Assertion.USER_CONFIRMED})


class RelationStatus(StrEnum):
    ACTIVE = "active"
    RETRACTED = "retracted"


class AssertionChangeReason(StrEnum):
    QUOTE_VERIFIED = "quote_verified"
    USER_CONFIRMED = "user_confirmed"
    USER_REJECTED = "user_rejected"
    USER_RESTORED = "user_restored"
    VERIFICATION_FAILED = "verification_failed"
    SOURCE_RETRACTED = "source_retracted"


class RelationDecisionKind(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class TombstoneReason(StrEnum):
    USER_DELETE = "user_delete"
    RETENTION = "retention"
    PROJECT_DELETE = "project_delete"
    ACCOUNT_DELETE = "account_delete"
    MERGE_SPLIT = "merge_split"
    RETRACTED = "retracted"
    REJECTED = "rejected"


class DeletionScope(StrEnum):
    CONVERSATION = "conversation"
    ALL_CONVERSATIONS = "all_conversations"
    LEARNING_PROGRESS = "learning_progress"
    PROJECT = "project"
    ACCOUNT = "account"
    RETENTION_EXPIRY = "retention_expiry"


class EntityRole(StrEnum):
    INTRODUCES = "introduces"
    USES_METHOD = "uses_method"
    EVALUATES_ON = "evaluates_on"
    COMPARES_AGAINST = "compares_against"  # RIE data, not a graph relationship
    REPORTS_METRIC = "reports_metric"  # RIE data, not a graph relationship


class SpanVerification(StrEnum):
    EXACT = "exact"
    FUZZY = "fuzzy"
    UNVERIFIED = "unverified"


class SpanLocation(StrEnum):
    ABSTRACT = "abstract"
    BODY_TEXT = "body_text"
    TABLE = "table"
    FIGURE_CAPTION = "figure_caption"
    METADATA = "metadata"
    LATEX_SOURCE = "latex_source"


class ResearchGroupKind(StrEnum):
    INSTITUTION = "institution"
    LAB = "lab"
    CONSORTIUM = "consortium"
    UNKNOWN = "unknown"
