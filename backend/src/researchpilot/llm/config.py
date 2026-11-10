"""Task -> {provider, model, parameters} configuration (ARCHITECTURE §4.2).

The initial configuration is provisional until decision D1 is approved; the flag travels
into every ``LLMResult`` and run manifest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class TaskModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    max_output_tokens: int = 16000
    parameters: dict[str, Any] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    provisional: bool
    defaults: TaskModelConfig
    tasks: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def for_task(self, task: str) -> TaskModelConfig:
        if task not in self.tasks:
            raise KeyError(f"LLM task {task!r} is not configured")
        merged = self.defaults.model_dump()
        override = self.tasks[task] or {}
        params = {**merged.get("parameters", {}), **override.get("parameters", {})}
        merged.update({k: v for k, v in override.items() if k != "parameters"})
        merged["parameters"] = params
        return TaskModelConfig.model_validate(merged)

    def with_provider(self, provider: str, model: str = "fake") -> LLMConfig:
        """Same tasks, all routed to another provider (used for the fake-provider swap)."""
        tasks = {
            name: {**(cfg or {}), "provider": provider, "model": model}
            for name, cfg in self.tasks.items()
        }
        defaults = self.defaults.model_copy(update={"provider": provider, "model": model})
        return self.model_copy(update={"defaults": defaults, "tasks": tasks})

    def manifest(self) -> dict[str, Any]:
        """What a run manifest records about models (R0-8)."""
        return {
            "config_version": self.version,
            "provisional": self.provisional,
            "tasks": {
                name: {"provider": c.provider, "model": c.model}
                for name in sorted(self.tasks)
                for c in [self.for_task(name)]
            },
        }


def load_llm_config(path: Path) -> LLMConfig:
    with path.open(encoding="utf-8") as fh:
        return LLMConfig.model_validate(yaml.safe_load(fh))
