"""Executes a run's LangGraph graph with the Postgres checkpointer (durable across restarts)."""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.db.session import session_scope
from researchpilot.domain.enums import RunStatus, Workflow
from researchpilot.llm.gateway import LLMGateway
from researchpilot.runs import service
from researchpilot.workflows.base import WorkflowDeps
from researchpilot.workflows.registry import WORKFLOWS


class WorkflowRunner:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        llm: LLMGateway,
        checkpointer: AsyncPostgresSaver,
    ) -> None:
        self._sessions = sessions
        self._llm = llm
        self._checkpointer = checkpointer

    async def execute(self, run_id: uuid.UUID, resume: dict[str, Any] | None = None) -> RunStatus:
        async with session_scope(self._sessions) as session:
            row = (
                await session.execute(
                    sa.text("SELECT workflow, status, config FROM research_runs WHERE id = :id"),
                    {"id": run_id},
                )
            ).one()
            if RunStatus(row.status) in service.TERMINAL:
                return RunStatus(row.status)  # e.g. cancelled while queued
            await service.mark_running(session, run_id)

        spec = WORKFLOWS[Workflow(row.workflow)]
        deps = WorkflowDeps(
            run_id=run_id, config=dict(row.config), sessions=self._sessions, llm=self._llm
        )
        graph = spec.build(deps).compile(checkpointer=self._checkpointer)
        thread = {"configurable": {"thread_id": str(run_id)}}

        snapshot = await graph.aget_state(thread)
        graph_input: Any
        if resume is not None:
            graph_input = Command(resume=resume)
        elif snapshot.next:
            if snapshot.interrupts:  # already paused (e.g. retried after recording the pause)
                return await self._pause(run_id, snapshot.interrupts[0].value)
            graph_input = None  # crashed mid-run: continue from the last checkpoint
            await deps.event("run.resumed", "Picking up where the run left off")
        else:
            graph_input = spec.initial_state(deps.config)
            await deps.event("run.started", "Started")

        result = await graph.ainvoke(graph_input, thread)
        if "__interrupt__" in result:
            return await self._pause(run_id, result["__interrupt__"][0].value)

        async with session_scope(self._sessions) as session:
            stopped = result.get("outcome") == "stopped"
            status = RunStatus.CANCELLED if stopped else RunStatus.SUCCEEDED
            await service.finish(
                session, run_id, status, "Stopped at your request" if stopped else "Finished"
            )
        return status

    async def _pause(self, run_id: uuid.UUID, value: dict[str, Any]) -> RunStatus:
        async with session_scope(self._sessions) as session:
            await service.open_checkpoint(
                session, run_id, str(value.get("name", "checkpoint")), value
            )
        return RunStatus.AWAITING_APPROVAL
