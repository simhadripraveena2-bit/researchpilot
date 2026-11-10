"""Provider-neutral LLM types (ARCHITECTURE §4.2).

Nothing in this module refers to a specific provider or model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class StopReason(StrEnum):
    COMPLETE = "complete"
    MAX_TOKENS = "max_tokens"
    REFUSAL = "refusal"
    OTHER = "other"


@dataclass(frozen=True)
class PromptRef:
    id: str
    version: int

    def __str__(self) -> str:
        return f"{self.id}.v{self.version}"


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0


@dataclass(frozen=True)
class LLMCapabilities:
    structured_output: bool = True
    streaming: bool = False
    batch: bool = False
    prompt_caching: bool = False
    max_context_tokens: int | None = None


@dataclass(frozen=True)
class LLMResult[R: BaseModel]:
    output: R
    task: str
    provider: str
    model: str
    prompt: PromptRef
    provisional: bool
    usage: LLMUsage
    attempts: int
    raw_text: str = field(repr=False, default="")


@dataclass(frozen=True)
class LLMChunk:
    """A streamed text delta; the final chunk carries the validated result."""

    text: str
    final: LLMResult[Any] | None = None


class LLMError(Exception):
    """Base for gateway errors. Never treated as an empty result by callers."""

    def __init__(self, message: str, *, task: str | None = None, **details: Any) -> None:
        super().__init__(message)
        self.task = task
        self.details = details


class LLMNotConfigured(LLMError):
    pass


class LLMRefusal(LLMError):
    pass


class LLMTruncated(LLMError):
    pass


class LLMOutputInvalid(LLMError):
    """Schema or semantic validation still failed after the single repair attempt."""


class LLMProviderError(LLMError):
    """Transport/API failure from a provider (after the adapter's own retries)."""

    def __init__(self, message: str, *, retryable: bool, task: str | None = None, **d: Any) -> None:
        super().__init__(message, task=task, **d)
        self.retryable = retryable
