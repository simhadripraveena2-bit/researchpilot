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
    Paper,
    PaperAuthor,
    PaperDate,
    PaperIdentifier,
    PaperManifestation,
    PaperSourceLink,
    PaperVersion,
    ProjectItem,
)
from researchpilot.db.models.runs import Checkpoint, ResearchRun, RunEvent, TaskExecution
from researchpilot.db.models.sources import HttpCacheEntry, SourceRateLimit, SourceRecord

__all__ = [
    "ArxivAnnouncementLog",
    "Checkpoint",
    "Claim",
    "ClaimEvidence",
    "ClaimVerification",
    "DomainEvent",
    "DomainEventDelivery",
    "GraphNode",
    "HttpCacheEntry",
    "Job",
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
    "RelationEndpointRule",
    "RelationRegistry",
    "ResearchItem",
    "ResearchObjective",
    "ResearchRun",
    "RunEvent",
    "SourceRateLimit",
    "SourceRecord",
    "StructuralRelation",
    "TaskExecution",
    "User",
]
