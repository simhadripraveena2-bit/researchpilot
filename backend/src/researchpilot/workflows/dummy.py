"""R0 dummy workflow: proves events, the LLM gateway, a human checkpoint and durability.

prepare (LLM gateway call via the configured provider) -> approval (interrupt) -> finish
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel

from researchpilot.llm.types import PromptRef
from researchpilot.workflows.base import WorkflowDeps, WorkflowSpec

ECHO_PROMPT = PromptRef("system/echo", 1)


class EchoOutput(BaseModel):
    echo: str


class DummyState(TypedDict, total=False):
    text: str
    echo: str
    decision: dict[str, Any]
    outcome: str


def build(deps: WorkflowDeps) -> StateGraph[DummyState]:
    async def prepare(state: DummyState) -> DummyState:
        await deps.event("step.started", "Preparing a short test run")
        pause = float(deps.config.get("pause_seconds", 0))
        if pause:
            await asyncio.sleep(pause)  # used by durability and cancellation tests
        await deps.ensure_not_cancelled()
        result = await deps.llm.generate_structured(
            "dummy_echo", ECHO_PROMPT, {"text": state["text"]}, EchoOutput
        )
        await deps.event(
            "step.completed",
            "Checked the connection to the language model",
            provider=result.provider,
            provisional=result.provisional,
        )
        return {"echo": result.output.echo}

    async def approval(state: DummyState) -> DummyState:
        decision = interrupt(
            {
                "name": "approve_test_run",
                "question": "The test run is ready to finish. Continue?",
                "echo": state.get("echo"),
            }
        )
        return {"decision": decision}

    async def finish(state: DummyState) -> DummyState:
        await deps.ensure_not_cancelled()
        rejected = state.get("decision", {}).get("status") == "rejected"
        return {"outcome": "stopped" if rejected else "completed"}

    graph: StateGraph[DummyState] = StateGraph(DummyState)
    graph.add_node("prepare", prepare)
    graph.add_node("approval", approval)
    graph.add_node("finish", finish)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "approval")
    graph.add_edge("approval", "finish")
    graph.add_edge("finish", END)
    return graph


def initial_state(config: dict[str, Any]) -> dict[str, Any]:
    return {"text": str(config.get("text", "ResearchPilot foundation check"))}


SPEC = WorkflowSpec(name="dummy", version="1", build=build, initial_state=initial_state)
