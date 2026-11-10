"""UUIDv7 identifiers (time-ordered), used for every primary key (ARCHITECTURE §12.2).

Python 3.12/3.13 have no stdlib ``uuid7``; this follows RFC 9562 §5.7.
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    unix_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")  # 80 random bits
    value = (unix_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version 7
    value |= ((rand >> 68) & 0xFFF) << 64  # rand_a: 12 bits
    value |= 0b10 << 62  # RFC 4122 variant
    value |= rand & ((1 << 62) - 1)  # rand_b: 62 bits
    return uuid.UUID(int=value)
