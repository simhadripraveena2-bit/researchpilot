"""Provider SDKs and the Neo4j driver are confined to their adapters (R0-8, R0-10e)."""

from __future__ import annotations

import subprocess
import sys

from researchpilot.core.settings import BACKEND_ROOT


def _ruff(code: str, filename: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "TID251",
            "--stdin-filename",
            filename,
            "-",
        ],
        input=code,
        text=True,
        capture_output=True,
        cwd=BACKEND_ROOT,
        check=False,
    )


def test_anthropic_import_outside_adapter_fails_lint() -> None:
    result = _ruff("import anthropic\n", "src/researchpilot/services/example.py")
    assert result.returncode != 0
    assert "TID251" in result.stdout


def test_anthropic_import_inside_adapter_is_allowed() -> None:
    result = _ruff("import anthropic\n", "src/researchpilot/llm/adapters/anthropic_adapter.py")
    assert result.returncode == 0, result.stdout


def test_neo4j_import_outside_graph_adapter_fails_lint() -> None:
    result = _ruff("from neo4j import GraphDatabase\n", "src/researchpilot/agents/x.py")
    assert result.returncode != 0
    assert "TID251" in result.stdout


def test_neo4j_import_inside_graph_adapter_is_allowed() -> None:
    result = _ruff("import neo4j\n", "src/researchpilot/graph/adapters/neo4j/driver.py")
    assert result.returncode == 0, result.stdout
