"""Gateway pipeline with the deterministic fake provider (ARCHITECTURE §4.2, R0-8)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from researchpilot.core.settings import BACKEND_ROOT
from researchpilot.llm.adapters.base import RawCompletion
from researchpilot.llm.adapters.fake import FakeProviderAdapter
from researchpilot.llm.config import load_llm_config
from researchpilot.llm.gateway import StructuredLLMGateway, strict_json_schema
from researchpilot.llm.prompts import PromptRegistry
from researchpilot.llm.types import (
    LLMNotConfigured,
    LLMOutputInvalid,
    LLMRefusal,
    LLMTruncated,
    PromptRef,
    StopReason,
)

ECHO = PromptRef("system/echo", 1)
KEY = ("dummy_echo", str(ECHO))


class Echo(BaseModel):
    echo: str


class Nested(BaseModel):
    items: list[Echo]


def make_gateway(fake: FakeProviderAdapter) -> StructuredLLMGateway:
    config = load_llm_config(BACKEND_ROOT / "config" / "llm_tasks.yaml").with_provider("fake")
    return StructuredLLMGateway(config, PromptRegistry(BACKEND_ROOT / "prompts"), {"fake": fake})


async def test_valid_output_is_returned_with_attribution() -> None:
    fake = FakeProviderAdapter({KEY: [{"echo": "hello"}]})
    result = await make_gateway(fake).generate_structured(
        "dummy_echo", ECHO, {"text": "hello"}, Echo
    )
    assert result.output == Echo(echo="hello")
    assert (result.provider, result.model, result.attempts) == ("fake", "fake", 1)
    assert result.provisional is True
    assert "hello" in fake.calls[0].messages[0].content
    assert fake.calls[0].json_schema["additionalProperties"] is False


async def test_one_repair_attempt_then_success() -> None:
    fake = FakeProviderAdapter({KEY: ["not json", {"echo": "fixed"}]})
    result = await make_gateway(fake).generate_structured("dummy_echo", ECHO, {"text": "x"}, Echo)
    assert result.output.echo == "fixed"
    assert result.attempts == 2
    repair = fake.calls[1].messages
    assert [m.role for m in repair] == ["user", "assistant", "user"]
    assert "not valid JSON" in repair[-1].content


async def test_still_invalid_after_repair_raises() -> None:
    fake = FakeProviderAdapter({KEY: [{"wrong": 1}, {"still": "wrong"}]})
    with pytest.raises(LLMOutputInvalid) as err:
        await make_gateway(fake).generate_structured("dummy_echo", ECHO, {"text": "x"}, Echo)
    assert err.value.details["problems"]
    assert len(fake.calls) == 2  # exactly one repair attempt


async def test_semantic_validation_failure_triggers_repair() -> None:
    fake = FakeProviderAdapter({KEY: [{"echo": "bad"}, {"echo": "good"}]})

    def must_be_good(out: Echo) -> list[str]:
        return [] if out.echo == "good" else ["echo must equal the input text"]

    result = await make_gateway(fake).generate_structured(
        "dummy_echo", ECHO, {"text": "good"}, Echo, semantic_validator=must_be_good
    )
    assert result.output.echo == "good"
    assert "echo must equal the input text" in fake.calls[1].messages[-1].content


@pytest.mark.parametrize(
    ("stop", "error"), [(StopReason.REFUSAL, LLMRefusal), (StopReason.MAX_TOKENS, LLMTruncated)]
)
async def test_refusal_and_truncation_are_errors_not_empty_results(
    stop: StopReason, error: type[Exception]
) -> None:
    fake = FakeProviderAdapter({KEY: [RawCompletion(text="", stop_reason=stop)]})
    with pytest.raises(error):
        await make_gateway(fake).generate_structured("dummy_echo", ECHO, {"text": "x"}, Echo)


async def test_unconfigured_task_is_rejected() -> None:
    with pytest.raises(LLMNotConfigured):
        await make_gateway(FakeProviderAdapter()).generate_structured(
            "no_such_task", ECHO, {}, Echo
        )


async def test_streaming_yields_deltas_then_validated_result() -> None:
    fake = FakeProviderAdapter({KEY: [{"echo": "streamed text"}]})
    chunks = [
        c
        async for c in make_gateway(fake).stream_structured("dummy_echo", ECHO, {"text": "x"}, Echo)
    ]
    assert "".join(c.text for c in chunks) == '{"echo": "streamed text"}'
    final = chunks[-1].final
    assert final is not None and final.output.echo == "streamed text"


def test_strict_schema_closes_nested_objects() -> None:
    schema = strict_json_schema(Nested)
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Echo"]["additionalProperties"] is False


def test_prompt_files_declare_their_own_ref(tmp_path: Path) -> None:
    (tmp_path / "system").mkdir()
    (tmp_path / "system" / "echo.v2.yaml").write_text(
        "id: system/echo\nversion: 1\nsystem: s\nuser: u\n"
    )
    with pytest.raises(ValueError, match="does not declare"):
        PromptRegistry(tmp_path).get(PromptRef("system/echo", 2))
