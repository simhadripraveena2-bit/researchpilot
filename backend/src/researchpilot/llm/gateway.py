"""The LLM gateway: the only way business logic calls a language model (ARCHITECTURE §4.2).

Callers name a *task*; provider and model come from ``LLMConfig``. Every call runs the same
provider-independent pipeline:

    render prompt -> adapter.complete -> stop-reason checks -> JSON parse ->
    Pydantic validation -> semantic validation -> (one repair attempt) -> LLMResult

Refusals and truncation are raised as errors, never returned as empty results.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from researchpilot.core.logging import get_logger
from researchpilot.llm.adapters.base import CompletionRequest, Message, ProviderAdapter
from researchpilot.llm.config import LLMConfig
from researchpilot.llm.prompts import PromptRegistry
from researchpilot.llm.types import (
    LLMCapabilities,
    LLMChunk,
    LLMError,
    LLMNotConfigured,
    LLMOutputInvalid,
    LLMRefusal,
    LLMResult,
    LLMTruncated,
    LLMUsage,
    PromptRef,
    StopReason,
    T,
)

# A semantic validator returns human-readable problems (empty list = valid). Examples in later
# releases: referenced item IDs exist in the project, quotes verify, numbers match evidence.
SemanticValidator = Callable[[Any], list[str]]

_REPAIR_INSTRUCTION = (
    "Your previous answer was rejected by validation. Return a corrected JSON object that "
    "matches the schema exactly and fixes these problems:\n{problems}"
)


class LLMGateway(Protocol):
    async def generate_structured(
        self,
        task: str,
        prompt: PromptRef,
        inputs: Mapping[str, Any],
        schema: type[T],
        *,
        semantic_validator: SemanticValidator | None = None,
    ) -> LLMResult[T]: ...

    def stream_structured(
        self, task: str, prompt: PromptRef, inputs: Mapping[str, Any], schema: type[T]
    ) -> AsyncIterator[LLMChunk]: ...

    def capabilities(self, task: str) -> LLMCapabilities: ...


def strict_json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """JSON schema for structured output: every object closed (additionalProperties false)."""
    raw = schema.model_json_schema()

    def close(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node.setdefault("additionalProperties", False)
            for value in node.values():
                close(value)
        elif isinstance(node, list):
            for value in node:
                close(value)

    close(raw)
    return raw


class StructuredLLMGateway:
    def __init__(
        self,
        config: LLMConfig,
        prompts: PromptRegistry,
        adapters: Mapping[str, ProviderAdapter],
    ) -> None:
        self._config = config
        self._prompts = prompts
        self._adapters = dict(adapters)

    @property
    def config(self) -> LLMConfig:
        return self._config

    def _adapter_for(self, task: str) -> tuple[ProviderAdapter, str]:
        try:
            task_cfg = self._config.for_task(task)
        except KeyError as exc:
            raise LLMNotConfigured(str(exc), task=task) from exc
        adapter = self._adapters.get(task_cfg.provider)
        if adapter is None:
            raise LLMNotConfigured(
                f"provider {task_cfg.provider!r} for task {task!r} is not available", task=task
            )
        return adapter, task_cfg.model

    def capabilities(self, task: str) -> LLMCapabilities:
        adapter, model = self._adapter_for(task)
        return adapter.capabilities(model)

    def _request(
        self,
        task: str,
        prompt: PromptRef,
        inputs: Mapping[str, Any],
        schema: type[BaseModel],
        messages: list[Message] | None = None,
    ) -> CompletionRequest:
        task_cfg = self._config.for_task(task)
        rendered = self._prompts.get(prompt)
        return CompletionRequest(
            task=task,
            prompt_id=str(prompt),
            model=task_cfg.model,
            system=rendered.system,
            messages=messages or [Message("user", rendered.render_user(dict(inputs)))],
            json_schema=strict_json_schema(schema),
            max_output_tokens=task_cfg.max_output_tokens,
            parameters=task_cfg.parameters,
        )

    async def generate_structured(
        self,
        task: str,
        prompt: PromptRef,
        inputs: Mapping[str, Any],
        schema: type[T],
        *,
        semantic_validator: SemanticValidator | None = None,
    ) -> LLMResult[T]:
        adapter, model = self._adapter_for(task)
        log = get_logger(task=task, prompt=str(prompt), provider=adapter.name, model=model)
        request = self._request(task, prompt, inputs, schema)
        usage = LLMUsage()
        problems: list[str] = []
        for attempt in (1, 2):
            raw = await adapter.complete(request)
            usage = LLMUsage(
                usage.input_tokens + raw.usage.input_tokens,
                usage.output_tokens + raw.usage.output_tokens,
                usage.cached_input_tokens + raw.usage.cached_input_tokens,
            )
            if raw.stop_reason is StopReason.REFUSAL:
                log.warning("llm.refusal", attempt=attempt, details=raw.details)
                raise LLMRefusal("model declined the request", task=task, **raw.details)
            if raw.stop_reason is StopReason.MAX_TOKENS:
                raise LLMTruncated("output truncated at max_output_tokens", task=task)

            output, problems = self._validate(raw.text, schema, semantic_validator)
            if output is not None:
                log.info(
                    "llm.ok",
                    attempt=attempt,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                )
                return LLMResult(
                    output=output,
                    task=task,
                    provider=adapter.name,
                    model=raw.model or model,
                    prompt=prompt,
                    provisional=self._config.provisional,
                    usage=usage,
                    attempts=attempt,
                    raw_text=raw.text,
                )
            log.warning("llm.validation_failed", attempt=attempt, problems=problems)
            request = CompletionRequest(
                **{
                    **request.__dict__,
                    "messages": [
                        *request.messages,
                        Message("assistant", raw.text),
                        Message("user", _REPAIR_INSTRUCTION.format(problems="\n".join(problems))),
                    ],
                }
            )
        raise LLMOutputInvalid(
            "output failed validation after one repair attempt", task=task, problems=problems
        )

    @staticmethod
    def _validate(
        text: str, schema: type[T], semantic_validator: SemanticValidator | None
    ) -> tuple[T | None, list[str]]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return None, [f"not valid JSON: {exc.msg} at position {exc.pos}"]
        try:
            output = schema.model_validate(data)
        except ValidationError as exc:
            return None, [
                f"{'.'.join(map(str, e['loc'])) or '<root>'}: {e['msg']}" for e in exc.errors()
            ]
        problems = semantic_validator(output) if semantic_validator else []
        return (output, []) if not problems else (None, problems)

    async def stream_structured(
        self, task: str, prompt: PromptRef, inputs: Mapping[str, Any], schema: type[T]
    ) -> AsyncIterator[LLMChunk]:
        adapter, model = self._adapter_for(task)
        if not adapter.capabilities(model).streaming:
            raise LLMError(f"provider {adapter.name!r} does not support streaming", task=task)
        request = self._request(task, prompt, inputs, schema)
        parts: list[str] = []
        async for delta in adapter.stream(request):
            parts.append(delta)
            yield LLMChunk(text=delta)
        text = "".join(parts)
        output, problems = self._validate(text, schema, None)
        if output is None:
            raise LLMOutputInvalid(
                "streamed output failed validation", task=task, problems=problems
            )
        yield LLMChunk(
            text="",
            final=LLMResult(
                output=output,
                task=task,
                provider=adapter.name,
                model=model,
                prompt=prompt,
                provisional=self._config.provisional,
                usage=LLMUsage(),
                attempts=1,
                raw_text=text,
            ),
        )
