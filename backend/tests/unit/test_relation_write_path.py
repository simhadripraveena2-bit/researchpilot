"""RelationWriter is the only write path for relationship rows (ARCHITECTURE §12.5).

A source scan: outside ``researchpilot/relations/`` no code inserts into, updates or deletes
from a relationship table, moves a HAS_VERSION link, or uses a relationship ORM model.
(Deleting a project or paper is allowed: the database cascades and writes markers.)
"""

from __future__ import annotations

import re
from pathlib import Path

from researchpilot.core.settings import BACKEND_ROOT
from researchpilot.relations import registry

SRC = BACKEND_ROOT / "src" / "researchpilot"
ALLOWED_DIRS = (SRC / "relations", SRC / "db" / "models")

RELATION_TABLES = sorted(
    {s.source_table for s in registry.AVAILABLE if s.source_table != "paper_manifestations"}
    | {"relation_decisions", "relation_suppressions", "relation_assertion_log", "entity_tombstones"}
)
WRITE = re.compile(
    r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(" + "|".join(RELATION_TABLES) + r")\b",
    re.IGNORECASE,
)
MOVE_VERSION = re.compile(r"UPDATE\s+paper_manifestations\s+SET\s+paper_id", re.IGNORECASE)
ORM_MODELS = re.compile(
    r"\b(Citation|PaperAuthor|AuthorAffiliation|EntityLink|ResearchRelation|StructuralRelation|"
    r"RelationDecision|RelationSuppression|RelationAssertionLog|EntityTombstone)\b"
)


def violations(path: Path, text: str) -> list[str]:
    found = [f"{path}: {m.group(0)}" for m in WRITE.finditer(text)]
    found += [f"{path}: {m.group(0)}" for m in MOVE_VERSION.finditer(text)]
    if "researchpilot.db.models" in text:
        found += [f"{path}: uses {m.group(0)}" for m in ORM_MODELS.finditer(text)]
    return found


def test_only_the_relations_package_writes_relationships() -> None:
    problems: list[str] = []
    for path in SRC.rglob("*.py"):
        if any(path.is_relative_to(d) for d in ALLOWED_DIRS):
            continue
        problems += violations(path.relative_to(SRC), path.read_text())
    assert problems == []


def test_the_scan_catches_direct_writes() -> None:
    bad = (
        'sa.text("INSERT INTO research_relations (id) VALUES (:i)")\n'
        'sa.text("update project_items set item_id = :s")\n'
        'sa.text("UPDATE paper_manifestations SET paper_id = :p")\n'
        "from researchpilot.db.models import StructuralRelation\n"
    )
    assert len(violations(Path("x.py"), bad)) == 4
    assert violations(Path("x.py"), 'sa.text("SELECT * FROM citations")') == []
