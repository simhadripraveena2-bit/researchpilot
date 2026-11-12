"""Deterministic edge ids and suppression fingerprints (pure)."""

from __future__ import annotations

import uuid

from researchpilot.relations import registry
from researchpilot.relations.ids import fingerprint, normalize_text, relation_uid

A, B = uuid.UUID(int=1), uuid.UUID(int=2)


def test_edge_ids_are_stable_and_distinguish_every_part() -> None:
    uid = relation_uid("CITES", "citations", A, B)
    assert uid == relation_uid("CITES", "citations", A, B)
    assert uid.version == 5
    assert (
        len(
            {
                uid,
                relation_uid("CITES", "citations", B, A),
                relation_uid("AUTHORED_BY", "citations", A, B),
                relation_uid("CITES", "paper_authors", A, B),
                relation_uid("CITES", "citations", A, B, "q"),
            }
        )
        == 5
    )


def test_fingerprints_ignore_case_accents_punctuation_and_spacing() -> None:
    assert normalize_text("  Only SMALL   data-sets, naïvely! ") == "only small data sets naively"
    assert fingerprint("RELATED_TO", A, B, "Only small datasets") == fingerprint(
        "RELATED_TO", A, B, "only  SMALL datasets!"
    )
    assert fingerprint("RELATED_TO", A, B, "x") != fingerprint("RELATED_TO", A, None, "x")
    assert "small" not in fingerprint("RELATED_TO", A, B, "small")  # no content stored


def test_code_registry_has_one_source_per_type() -> None:
    types = [s.type for s in registry.SPECS]
    assert len(types) == len(set(types)) == 18
    shared = {s.source_table for s in registry.SPECS if s.type_discriminator}
    assert shared == {"entity_links", "research_relations", "structural_relations"}
    assert registry.allowed("RELATED_TO", "Gap", "Paper")
    assert not registry.allowed("CITES", "Paper", "Author")
