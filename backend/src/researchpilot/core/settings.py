"""Environment-based configuration (ARCHITECTURE §2.3).

Secrets are typed as ``SecretStr`` so they never appear in reprs, and their values are
registered with the logging redactor (``core.logging``).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[3]


class AuthMode(StrEnum):
    """Authentication mode. ``disabled`` is only allowed on a localhost bind (R0-9)."""

    DISABLED = "disabled"
    OIDC = "oidc"
    PASSWORD = "password"  # noqa: S105 - a mode name, not a password


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = (
        "postgresql+psycopg://researchpilot:researchpilot@localhost:5432/researchpilot"
    )

    bind_host: str = "127.0.0.1"
    bind_port: int = 8000
    auth_mode: AuthMode = AuthMode.DISABLED
    # Set only by the local Docker Compose stack: the API binds 0.0.0.0 *inside* its
    # container, and Compose publishes ports on 127.0.0.1 only (checked by a test).
    container_local: bool = False

    storage_dir: Path = Path("./var/storage")
    llm_config_path: Path = BACKEND_ROOT / "config" / "llm_tasks.yaml"
    prompts_dir: Path = BACKEND_ROOT / "prompts"
    # Route every LLM task to the deterministic fake provider (tests, offline development, and
    # the R0 stack while decision D1 is open). Recorded in run manifests.
    llm_force_fake: bool = False

    worker_poll_seconds: float = 1.0
    job_heartbeat_seconds: float = 5.0
    job_stale_after_seconds: float = 30.0
    git_sha: str = "dev"
    # OpenAlex (D24): "basic" uses only free/basic features; "premium" also enables the
    # created-date filters for newly indexed works. Daily spend cap in USD for metered calls.
    openalex_capabilities: Literal["basic", "premium"] = "basic"
    openalex_daily_budget_usd: float = 0.10

    # Polite-pool contact address for scholarly APIs (OpenAlex, Crossref, Unpaywall).
    contact_email: str | None = None

    # Secrets: never logged, never returned by the API.
    anthropic_api_key: SecretStr | None = None
    s2_api_key: SecretStr | None = None
    openalex_api_key: SecretStr | None = None
    github_token: SecretStr | None = None
    hf_token: SecretStr | None = None
    session_secret: SecretStr | None = Field(default=None, description="Signing key (hosted mode)")

    def secret_values(self) -> list[str]:
        """All configured secret values, for the log redactor."""
        values: list[str] = []
        for name, field in type(self).model_fields.items():
            if field.annotation in (SecretStr, SecretStr | None):
                value = getattr(self, name)
                if isinstance(value, SecretStr) and value.get_secret_value():
                    values.append(value.get_secret_value())
        return values


@lru_cache
def get_settings() -> Settings:
    return Settings()
