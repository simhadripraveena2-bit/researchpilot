"""Starting and retrying discovery runs (the run lifecycle itself is the shared one)."""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from pydantic import ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.core.errors import Conflict, NotFound, ValidationFailed
from researchpilot.domain.enums import SourceName, Workflow
from researchpilot.jobs.queue import enqueue
from researchpilot.runs.events import record_event
from researchpilot.runs.service import create_run
from researchpilot.services.discovery.planner import SEARCHABLE, PlanOptions

ACTIVE = ("queued", "running", "awaiting_approval")


class DiscoveryConfig(PlanOptions):
    """Options for one discovery run (stored as the run's config)."""

    model_config = ConfigDict(extra="forbid")
    confirm_plan: bool = True  # pause for the user to confirm the search plan
    release_window_days: int = Field(default=30, ge=1, le=366)

    @field_validator("sources")
    @classmethod
    def _searchable(cls, value: list[SourceName] | None) -> list[SourceName] | None:
        unknown = [s for s in value or [] if s not in SEARCHABLE]
        if unknown:
            raise ValueError(f"{', '.join(s.value for s in unknown)} cannot be searched by topic")
        return value


async def start_discovery(
    session: AsyncSession,
    project_id: uuid.UUID,
    config: dict[str, Any],
    manifest: dict[str, Any],
) -> uuid.UUID:
    try:
        options = DiscoveryConfig.model_validate(config)
    except ValueError as exc:
        raise ValidationFailed(f"invalid discovery options: {exc}") from exc
    active = await session.scalar(
        sa.text(
            "SELECT o.version FROM research_objectives o JOIN projects p "
            "ON p.active_objective_id = o.id WHERE p.id = :p FOR UPDATE OF p"
        ),
        {"p": project_id},
    )
    if active is None:
        raise ValidationFailed(
            "this project has no research objective yet; create one before searching"
        )
    running = await session.scalar(
        sa.text(
            "SELECT id FROM research_runs WHERE project_id = :p AND workflow = 'discovery' "
            "AND status = ANY(:active) LIMIT 1"
        ),
        {"p": project_id, "active": list(ACTIVE)},
    )
    if running is not None:
        raise Conflict("a discovery run is already in progress", run_id=str(running))
    return await create_run(
        session,
        project_id,
        Workflow.DISCOVERY,
        options.model_dump(mode="json", exclude_none=True),
        manifest,
    )


async def retry_discovery(session: AsyncSession, run_id: uuid.UUID) -> None:
    """Re-run a finished discovery run that failed or was partial: only failed or skipped
    searches are sent again and only failed hits are re-read; everything else is kept."""
    reopened = await session.scalar(
        sa.text(
            "UPDATE research_runs SET status = 'queued', finished_at = NULL, error = NULL "
            "WHERE id = :id AND workflow = 'discovery' "
            "AND status IN ('failed', 'partially_succeeded') RETURNING project_id"
        ),
        {"id": run_id},
    )
    if reopened is None:
        status = await session.scalar(
            sa.text("SELECT status FROM research_runs WHERE id = :id"), {"id": run_id}
        )
        if status is None:
            raise NotFound("run not found")
        raise Conflict(
            f"only failed or partially successful discovery runs can be retried (this one is "
            f"{status})"
        )
    await session.execute(
        sa.text(
            "UPDATE search_results r SET outcome = 'pending', outcome_detail = NULL, "
            "decided_at = NULL FROM search_queries q WHERE q.id = r.query_id AND q.run_id = :id "
            "AND r.outcome = 'failed'"
        ),
        {"id": run_id},
    )
    await record_event(session, run_id, "run.retrying", "Trying the failed searches again")
    await enqueue(session, "run_workflow", {"run_id": str(run_id)})


__all__ = ["DiscoveryConfig", "retry_discovery", "start_discovery"]
