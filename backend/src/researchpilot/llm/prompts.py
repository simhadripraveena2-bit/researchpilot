"""Versioned, provider-neutral prompt files: ``prompts/<group>/<name>.v<N>.yaml``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

import yaml

from researchpilot.llm.types import PromptRef


@dataclass(frozen=True)
class Prompt:
    ref: PromptRef
    system: str
    user_template: str

    def render_user(self, inputs: dict[str, Any]) -> str:
        values = {
            k: v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
            for k, v in inputs.items()
        }
        return Template(self.user_template).substitute(values)


class PromptRegistry:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._cache: dict[PromptRef, Prompt] = {}

    def get(self, ref: PromptRef) -> Prompt:
        if ref not in self._cache:
            path = self._root / f"{ref.id}.v{ref.version}.yaml"
            if not path.is_file():
                raise FileNotFoundError(f"prompt {ref} not found at {path}")
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if data.get("id") != ref.id or data.get("version") != ref.version:
                raise ValueError(f"prompt file {path} does not declare {ref}")
            self._cache[ref] = Prompt(ref=ref, system=data["system"], user_template=data["user"])
        return self._cache[ref]
