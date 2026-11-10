"""Private, content-addressed storage rejects traversal and malformed keys (S6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from researchpilot.storage.object_store import LocalObjectStore


def test_put_get_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    key = store.put(b"%PDF-1.7 test")
    assert store.put(b"%PDF-1.7 test") == key
    assert store.get(key) == b"%PDF-1.7 test"
    assert (tmp_path / key[:2] / key).is_file()


@pytest.mark.parametrize("key", ["../../etc/passwd", "ab", "Z" * 64, "/abs/path"])
def test_invalid_keys_are_rejected(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError, match="invalid object key"):
        LocalObjectStore(tmp_path).get(key)
