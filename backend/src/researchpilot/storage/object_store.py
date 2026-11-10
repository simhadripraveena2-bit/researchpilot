"""Private, content-addressed file storage (ARCHITECTURE §2.6, S6).

Files are never served statically: the API streams them only after authorization.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Protocol

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ObjectStore(Protocol):
    def put(self, data: bytes) -> str: ...

    def get(self, sha256: str) -> bytes: ...

    def exists(self, sha256: str) -> bool: ...


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path(self, sha256: str) -> Path:
        if not _SHA256.match(sha256):  # rejects traversal attempts and malformed keys
            raise ValueError("invalid object key")
        return self._root / sha256[:2] / sha256

    def put(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        path = self._path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return digest

    def get(self, sha256: str) -> bytes:
        return self._path(sha256).read_bytes()

    def exists(self, sha256: str) -> bool:
        return self._path(sha256).exists()
