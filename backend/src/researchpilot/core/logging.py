"""Structured JSON logging with secret redaction (R0-5).

Two redaction rules, applied recursively to every event:
1. any value equal to, or containing, a configured secret is masked;
2. values under sensitive-looking keys (api_key, token, password, secret, authorization,
   cookie) are masked regardless of content.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable, MutableMapping
from typing import Any

import structlog

REDACTED = "***"
_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|token|password|passwd|secret|authorization|cookie)", re.I
)


class SecretRedactor:
    def __init__(self, secrets: Iterable[str]) -> None:
        # Longest first so overlapping secrets are fully masked.
        self._secrets = sorted({s for s in secrets if s and len(s) >= 4}, key=len, reverse=True)

    def _scrub(self, value: Any, key: str | None = None) -> Any:
        if key is not None and _SENSITIVE_KEY.search(key) and value not in (None, ""):
            return REDACTED
        if isinstance(value, str):
            for secret in self._secrets:
                if secret in value:
                    value = value.replace(secret, REDACTED)
            return value
        if isinstance(value, dict):
            return {k: self._scrub(v, str(k)) for k, v in value.items()}
        if isinstance(value, list | tuple | set):
            return type(value)(self._scrub(v) for v in value)
        return value

    def __call__(
        self, logger: Any, method: str, event_dict: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        return {k: self._scrub(v, k if k != "event" else None) for k, v in event_dict.items()}


def configure_logging(
    level: str = "INFO", json: bool = True, secrets: Iterable[str] = (), stream: Any = None
) -> None:
    """Configure structlog. Call once at process start (API, worker, CLI)."""
    redactor = SecretRedactor(secrets)
    renderer: Any = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            redactor,  # after exception formatting, so tracebacks are scrubbed too
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=stream or sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(**context: Any) -> Any:
    return structlog.get_logger().bind(**context)
