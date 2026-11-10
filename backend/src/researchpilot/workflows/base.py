"""Workflow plumbing shared by all LangGraph workflows."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.db.session import session_scope
from researchpilot.llm.gateway import LLMGateway
from researchpilot.runs.events import record_event


@dataclass
class WorkflowDeps:
    run_id: uuid.UUID
    config: dict[str, Any]
    sessions: async_sessionmaker[AsyncSession]
    llm: LLMGateway

    async def event(self, type_: str, message: str, **data: Any) -> None:
        """Progress messages are committed immediately so the UI sees them live."""
        async with session_scope(self.sessions) as session:
            await record_event(session, self.run_id, type_, message, data=data)


# A workflow module exposes: build(deps) -> StateGraph (uncompiled), initial_state(config) -> dict
@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    version: str
    build: Callable[[WorkflowDeps], Any]
    initial_state: Callable[[dict[str, Any]], dict[str, Any]]
