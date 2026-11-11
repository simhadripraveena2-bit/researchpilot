"""All ORM models, imported so ``Base.metadata`` is complete (Alembic, tests)."""

from researchpilot.db.models.claims import Claim, ClaimEvidence, ClaimVerification
from researchpilot.db.models.events import DomainEvent, DomainEventDelivery
from researchpilot.db.models.graph import GraphNode, NodeSourceRegistry, ResearchItem
from researchpilot.db.models.identity import Project, ProjectMember, User
from researchpilot.db.models.jobs import Job
from researchpilot.db.models.matching import (
    PaperMatchDecision,
    PaperMergeEvent,
    PaperVersionLink,
)
from researchpilot.db.models.papers import (
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
    "ResearchItem",
    "ResearchRun",
    "RunEvent",
    "SourceRateLimit",
    "SourceRecord",
    "TaskExecution",
    "User",
]
