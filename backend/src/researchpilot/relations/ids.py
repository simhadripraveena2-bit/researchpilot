"""Deterministic edge identities for composite-key link tables (ARCHITECTURE §12.2)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid

# Must equal RELATION_NAMESPACE in alembic/rp_sql/relations_0009.py (tested).
RELATION_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://researchpilot.dev/ns/relations")


def relation_uid(
    type_: str, table: str, from_uid: uuid.UUID, to_uid: uuid.UUID, qualifier: str = ""
) -> uuid.UUID:
    """UUIDv5 of (type, table, from, to, qualifier): the same edge always gets the same uid,
    in PostgreSQL (``rp_relation_uid``) and in Neo4j after any resync or rebuild."""
    return uuid.uuid5(RELATION_NAMESPACE, f"{type_}|{table}|{from_uid}|{to_uid}|{qualifier}")


_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def normalize_text(text: str) -> str:
    """Case-, accent-, punctuation- and whitespace-insensitive form for fingerprints."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    return _SPACE.sub(" ", _PUNCT.sub(" ", folded)).strip()


def fingerprint(
    type_: str, from_uid: uuid.UUID, to_uid: uuid.UUID | None, text: str | None = None
) -> str:
    """Hash of type, endpoints and normalised text. Stores no content (one-way)."""
    basis = f"{type_}|{from_uid}|{to_uid or ''}|{normalize_text(text) if text else ''}"
    return hashlib.sha256(basis.encode()).hexdigest()
