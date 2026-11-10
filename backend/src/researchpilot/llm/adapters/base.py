"""Adapter contract: a provider turns a neutral request into raw text plus metadata."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from researchpilot.llm.types import LLMCapabilities, LLMUsage, StopReason


@dataclass(frozen=True)
class Message:
    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class CompletionRequest:
    task: str
    prompt_id: str
    model: str
    system: str
    messages: list[Message]
    json_schema: dict[str, Any]
    max_output_tokens: int
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawCompletion:
    text: str
    stop_reason: StopReason
    usage: LLMUsage = field(default_factory=LLMUsage)
    model: str | None = None  # model that actually served the request (may differ on fallback)
    details: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(Protocol):
    name: str

    def capabilities(self, model: str) -> LLMCapabilities: ...

    async def complete(self, request: CompletionRequest) -> RawCompletion: ...

    def stream(self, request: CompletionRequest) -> AsyncIterator[str]: ...
