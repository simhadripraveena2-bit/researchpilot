"""Anthropic adapter (first provider; the model choice stays provisional until D1).

Structured output uses ``output_config.format`` with a JSON schema; the gateway re-validates
the text with Pydantic. Server-side refusal fallbacks are enabled by default for models
that support them (``parameters.server_side_fallback: "default"``); set it to null to opt
out. Only this module imports the Anthropic SDK (ruff TID251).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import anthropic

from researchpilot.llm.adapters.base import CompletionRequest, RawCompletion
from researchpilot.llm.types import LLMCapabilities, LLMProviderError, LLMUsage, StopReason

_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_STOP_REASONS = {
    "end_turn": StopReason.COMPLETE,
    "stop_sequence": StopReason.COMPLETE,
    "max_tokens": StopReason.MAX_TOKENS,
    "refusal": StopReason.REFUSAL,
}


class AnthropicAdapter:
    name = "anthropic"

    def __init__(self, api_key: str | None, max_retries: int = 2, timeout_s: float = 600) -> None:
        # api_key=None lets the SDK resolve credentials from its own environment/profile.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, max_retries=max_retries, timeout=timeout_s
        )

    def capabilities(self, model: str) -> LLMCapabilities:
        return LLMCapabilities(
            structured_output=True,
            streaming=False,
            batch=True,
            prompt_caching=True,
            max_context_tokens=1_000_000,
        )

    def _kwargs(self, request: CompletionRequest) -> dict[str, Any]:
        params = dict(request.parameters)
        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": request.json_schema}
        }
        if effort := params.pop("effort", None):
            output_config["effort"] = effort
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            # Stable system prompt is cached; volatile inputs live in the messages.
            "system": [
                {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "output_config": output_config,
        }
        fallback = params.pop("server_side_fallback", "default")
        if fallback:
            kwargs["betas"] = [_FALLBACK_BETA]
            kwargs["fallbacks"] = fallback
        if params:
            raise ValueError(
                f"unsupported Anthropic parameters for {request.task}: {sorted(params)}"
            )
        return kwargs

    async def complete(self, request: CompletionRequest) -> RawCompletion:
        kwargs = self._kwargs(request)
        try:
            if "betas" in kwargs:
                response = await self._client.beta.messages.create(**kwargs)
            else:
                response = await self._client.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            raise LLMProviderError("rate limited", retryable=True, task=request.task) from exc
        except anthropic.APIStatusError as exc:
            raise LLMProviderError(
                f"provider error {exc.status_code}",
                retryable=exc.status_code >= 500,
                task=request.task,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMProviderError("connection error", retryable=True, task=request.task) from exc

        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        stop = _STOP_REASONS.get(str(response.stop_reason), StopReason.OTHER)
        details: dict[str, Any] = {}
        stop_details = getattr(response, "stop_details", None)
        if stop is StopReason.REFUSAL and stop_details is not None:
            details["refusal_category"] = getattr(stop_details, "category", None)
        usage = response.usage
        return RawCompletion(
            text=text,
            stop_reason=stop,
            usage=LLMUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            ),
            model=response.model,
            details=details,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        # Streaming lands with Ask & Learn (M1d); capabilities() reports streaming=False.
        raise NotImplementedError("streaming is not implemented for the Anthropic adapter yet")
        yield ""  # pragma: no cover - makes this an async generator
