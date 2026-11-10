"""R0-5: logs never contain configured secret values."""

from __future__ import annotations

import io
import json

import pytest
from pydantic import SecretStr

from researchpilot.core.logging import REDACTED, configure_logging, get_logger
from researchpilot.core.settings import Settings

SECRET = "sk-test-SUPERSECRET-123456"


def _capture() -> io.StringIO:
    stream = io.StringIO()
    settings = Settings(anthropic_api_key=SecretStr(SECRET), _env_file=None)
    configure_logging(level="DEBUG", json=True, secrets=settings.secret_values(), stream=stream)
    return stream


def test_secret_values_are_redacted_everywhere() -> None:
    stream = _capture()
    log = get_logger(component="test")
    log.info(f"calling provider with {SECRET}", nested={"deep": [f"x{SECRET}y"]}, plain=SECRET)
    try:
        raise RuntimeError(f"failure using key {SECRET}")
    except RuntimeError:
        log.exception("boom")
    output = stream.getvalue()
    assert SECRET not in output
    assert REDACTED in output
    for line in output.strip().splitlines():
        json.loads(line)  # every line is valid JSON


def test_sensitive_keys_are_masked_even_for_unknown_values() -> None:
    stream = _capture()
    get_logger().info(
        "request",
        headers={"Authorization": "Bearer abc"},
        api_key="whatever",
        password="hunter22",
        ok="visible",
    )
    record = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert record["headers"]["Authorization"] == REDACTED
    assert record["api_key"] == REDACTED
    assert record["password"] == REDACTED
    assert record["ok"] == "visible"


def test_settings_repr_hides_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "S2_API_KEY",
        "OPENALEX_API_KEY",
        "GITHUB_TOKEN",
        "HF_TOKEN",
        "SESSION_SECRET",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(anthropic_api_key=SecretStr(SECRET), _env_file=None)
    assert SECRET not in repr(settings)
    assert settings.secret_values() == [SECRET]
