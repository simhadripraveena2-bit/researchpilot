"""Deterministic fake provider for tests and offline development.

Responses are keyed by ``(task, prompt_id)`` and consumed in order; each can be a JSON
string, a dict (serialised), or a ``RawCompletion`` (to simulate refusals and truncation).
Every request is recorded in ``calls`` so tests can assert what the gateway sent.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from typing import Any

from researchpilot.llm.adapters.base import CompletionRequest, RawCompletion
from researchpilot.llm.types import LLMCapabilities, LLMUsage, StopReason

FakeResponse = str | dict[str, Any] | RawCompletion
Responder = Callable[[CompletionRequest], dict[str, Any]]


def _echo_responder(request: CompletionRequest) -> dict[str, Any]:
    """Deterministic answer for the R0 ``dummy_echo`` task (echoes the user's text)."""
    content = request.messages[0].content
    return {"echo": content.split(": ", 1)[1].strip() if ": " in content else content.strip()}


DEV_RESPONDERS: dict[str, Responder] = {"dummy_echo": _echo_responder}


class FakeProviderAdapter:
    name = "fake"

    def __init__(
        self,
        responses: dict[tuple[str, str], list[FakeResponse]] | None = None,
        responders: dict[str, Responder] | None = None,
    ) -> None:
        self._responses: dict[tuple[str, str], deque[FakeResponse]] = defaultdict(deque)
        self._responders = dict(responders or {})
        self.calls: list[CompletionRequest] = []
        for key, items in (responses or {}).items():
            self.add(key[0], key[1], *items)

    def add(self, task: str, prompt_id: str, *responses: FakeResponse) -> None:
        self._responses[(task, prompt_id)].extend(responses)

    def capabilities(self, model: str) -> LLMCapabilities:
        return LLMCapabilities(structured_output=True, streaming=True)

    def _next(self, request: CompletionRequest) -> RawCompletion:
        self.calls.append(request)
        queue = self._responses.get((request.task, request.prompt_id))
        if not queue and request.task in self._responders:
            queue = deque([self._responders[request.task](request)])
        if not queue:
            raise AssertionError(
                f"FakeProviderAdapter has no response for {(request.task, request.prompt_id)}"
            )
        item = queue.popleft()
        if isinstance(item, RawCompletion):
            return item
        text = item if isinstance(item, str) else json.dumps(item)
        return RawCompletion(
            text=text,
            stop_reason=StopReason.COMPLETE,
            usage=LLMUsage(input_tokens=10, output_tokens=5),
            model="fake",
        )

    async def complete(self, request: CompletionRequest) -> RawCompletion:
        return self._next(request)

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        text = self._next(request).text
        for i in range(0, len(text), 8):
            yield text[i : i + 8]
