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
from researchpilot.integrations.registry import Sources
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
        sources: Sources | None = None,
    ) -> None:
        self._sessions = sessions
        self._llm = llm
        self._checkpointer = checkpointer
        self._sources = sources

    async def execute(self, run_id: uuid.UUID, resume: dict[str, Any] | None = None) -> RunStatus:
        async with session_scope(self._sessions) as session:
            row = (
                await session.execute(
                    sa.text("SELECT workflow, status, config FROM research_runs WHERE id = :id"),
                    {"id": run_id},
                )
            ).one()
            if not await service.mark_running(session, run_id):
                return RunStatus(row.status)  # already finished, e.g. cancelled while queued

        spec = WORKFLOWS[Workflow(row.workflow)]
        deps = WorkflowDeps(
            run_id=run_id,
            config=dict(row.config),
            sessions=self._sessions,
            llm=self._llm,
            sources=self._sources,
        )
        graph = spec.build(deps).compile(checkpointer=self._checkpointer)
        thread = {"configurable": {"thread_id": str(run_id)}}

        try:
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
        except service.RunCancelled:
            return RunStatus.CANCELLED  # the run was cancelled while executing; nothing to do
        if "__interrupt__" in result:
            return await self._pause(run_id, result["__interrupt__"][0].value)

        outcome = result.get("outcome")
        status, message, error = {
            "stopped": (RunStatus.CANCELLED, "Stopped at your request", None),
            "failed": (
                RunStatus.FAILED,
                "Could not finish",
                {"message": str(result.get("error") or "the workflow failed")},
            ),
            "partial": (
                RunStatus.PARTIALLY_SUCCEEDED,
                "Finished, but some sources could not be searched",
                None,
            ),
        }.get(str(outcome), (RunStatus.SUCCEEDED, "Finished", None))
        async with session_scope(self._sessions) as session:
            finished = await service.finish(session, run_id, status, message, error)
        # A run cancelled after its last step keeps its CANCELLED status (finish is a no-op).
        return status if finished else RunStatus.CANCELLED

    async def _pause(self, run_id: uuid.UUID, value: dict[str, Any]) -> RunStatus:
        async with session_scope(self._sessions) as session:
            opened = await service.open_checkpoint(
                session, run_id, str(value.get("name", "checkpoint")), value
            )
        return RunStatus.AWAITING_APPROVAL if opened else RunStatus.CANCELLED
