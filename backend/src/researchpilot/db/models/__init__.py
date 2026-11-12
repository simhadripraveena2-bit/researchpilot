"""All ORM models, imported so ``Base.metadata`` is complete (Alembic, tests)."""

from researchpilot.db.models.claims import Claim, ClaimEvidence, ClaimVerification
from researchpilot.db.models.events import DomainEvent, DomainEventDelivery
from researchpilot.db.models.graph import (
    GraphNode,
    NodeSourceRegistry,
    RelationEndpointRule,
    RelationRegistry,
    ResearchItem,
    StructuralRelation,
)
from researchpilot.db.models.identity import Project, ProjectMember, User
from researchpilot.db.models.jobs import Job
from researchpilot.db.models.matching import (
    PaperMatchDecision,
    PaperMergeEvent,
    PaperVersionLink,
)
from researchpilot.db.models.objectives import ObjectiveSubQuestion, ResearchObjective
from researchpilot.db.models.papers import (
    ArxivAnnouncementLog,
    ManifestationAuthor,
    Paper,
    PaperDate,
    PaperIdentifier,
    PaperManifestation,
    PaperSourceLink,
    PaperVersion,
    ProjectItem,
)
from researchpilot.db.models.relations import (
    Author,
    AuthorAffiliation,
    Citation,
    DeletionLog,
    Entity,
    EntityLink,
    EntityTombstone,
    EvidenceSpan,
    PaperAuthor,
    RelationAssertionLog,
    RelationDecision,
    RelationSuppression,
    ResearchGroup,
    ResearchRelation,
)
from researchpilot.db.models.runs import Checkpoint, ResearchRun, RunEvent, TaskExecution
from researchpilot.db.models.search import SearchQuery, SearchResult
from researchpilot.db.models.sources import HttpCacheEntry, SourceRateLimit, SourceRecord

__all__ = [
    "ArxivAnnouncementLog",
    "Author",
    "AuthorAffiliation",
    "Checkpoint",
    "Citation",
    "Claim",
    "ClaimEvidence",
    "ClaimVerification",
    "DeletionLog",
    "DomainEvent",
    "DomainEventDelivery",
    "Entity",
    "EntityLink",
    "EntityTombstone",
    "EvidenceSpan",
    "GraphNode",
    "HttpCacheEntry",
    "Job",
    "ManifestationAuthor",
    "NodeSourceRegistry",
    "ObjectiveSubQuestion",
    "Paper",
    "PaperAuthor",
    "PaperDate",
    "PaperIdentifier",
    "PaperManifestation",
    "PaperMatchDecision",
    "PaperMergeEvent",
    "PaperSourceLink",
    "PaperVersion",
    "PaperVersionLink",
    "Project",
    "ProjectItem",
    "ProjectMember",
    "RelationAssertionLog",
    "RelationDecision",
    "RelationEndpointRule",
    "RelationRegistry",
    "RelationSuppression",
    "ResearchGroup",
    "ResearchItem",
    "ResearchObjective",
    "ResearchRelation",
    "ResearchRun",
    "RunEvent",
    "SearchQuery",
    "SearchResult",
    "SourceRateLimit",
    "SourceRecord",
    "StructuralRelation",
    "TaskExecution",
    "User",
]
