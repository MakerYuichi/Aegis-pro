"""
UUIDv7 generation for Python 3.11.

UUIDv7 is a time-ordered UUID: the first 48 bits are a Unix
millisecond timestamp, so UUIDs sort lexicographically by creation
time. Postgres indexes them as efficiently as a sequential key while
still being globally unique.

Python 3.14 adds uuid.uuid7() to the stdlib. Until this project moves
to 3.14+, this module provides the same output without pulling in a
third-party package. The orchestrator is the process that provisions
the supply-chain sandbox, so its own dependency list is part of the
trust surface — a one-line helper beats a new dependency.

Reference: RFC 9562, section 5.7.
"""
from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """
    Return a new UUIDv7.

    Layout (128 bits):
        48 bits  unix_ts_ms    milliseconds since the Unix epoch
         4 bits  version       0b0111
        12 bits  rand_a        random
         2 bits  variant       0b10
        62 bits  rand_b        random

    Monotonicity within a single millisecond is not guaranteed —
    two calls in the same millisecond may sort either way. For
    receipt IDs, timestamp granularity is enough; ordering within
    a millisecond is not a requirement.
    """
    unix_ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)

    value = (
        (unix_ts_ms << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0x2 << 62)
        | rand_b
    )
    return uuid.UUID(int=value)
