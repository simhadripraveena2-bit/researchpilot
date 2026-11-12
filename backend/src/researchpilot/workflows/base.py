"""Workflow plumbing shared by all LangGraph workflows."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.db.session import session_scope
from researchpilot.integrations.registry import Sources
from researchpilot.llm.gateway import LLMGateway
from researchpilot.runs.events import record_event
from researchpilot.runs.service import RunCancelled, is_cancelled


@dataclass
class WorkflowDeps:
    run_id: uuid.UUID
    config: dict[str, Any]
    sessions: async_sessionmaker[AsyncSession]
    llm: LLMGateway
    sources: Sources | None = None  # scholarly source clients (discovery workflows)

    async def ensure_not_cancelled(self) -> None:
        """Cooperative cancellation point: stop the workflow if its run was cancelled."""
        async with session_scope(self.sessions) as session:
            if await is_cancelled(session, self.run_id):
                raise RunCancelled(str(self.run_id))

    async def event(self, type_: str, message: str, **data: Any) -> None:
        """Progress messages are committed immediately so the UI sees them live. Every event is
        also a cancellation point."""
        async with session_scope(self.sessions) as session:
            if await is_cancelled(session, self.run_id):
                raise RunCancelled(str(self.run_id))
            await record_event(session, self.run_id, type_, message, data=data)


# A workflow module exposes: build(deps) -> StateGraph (uncompiled), initial_state(config) -> dict
@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    version: str
    build: Callable[[WorkflowDeps], Any]
    initial_state: Callable[[dict[str, Any]], dict[str, Any]]
