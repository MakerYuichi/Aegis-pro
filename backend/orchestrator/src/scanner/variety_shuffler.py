"""Deterministic variety shuffler — round-robin across files.

The scanner's file loop produces candidates in file order:
    models.py x 10, utils.py x 3, cookies.py x 1, status_codes.py x 1

A top-N selection that preserves insertion order starves every
single-file candidate behind the top-churn files. The shuffler
rearranges so:

    models.py, utils.py, cookies.py, status_codes.py,
    models.py, utils.py, models.py, ...

This is a scheduling change, not a scoring change. The score of
every candidate is unchanged; only the position in the queue is
reshuffled. The downstream Investigator gets the same score-sorted
view it had before, but interleaved by file.

Deterministic. Zero LLM. Instant.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, TypeVar

T = TypeVar("T")


def _default_key(c):
    """Default key: the file path.
    
    Handles both ScanCandidate (has root_file) and ScanOutcome
    (has .candidate.root_file). The runner passes ScanOutcome; a
    future caller might pass ScanCandidate. One default that works
    for both keeps the module honest about what it shuffles.
    """
    if hasattr(c, "root_file"):
        return c.root_file
    if hasattr(c, "candidate") and hasattr(c.candidate, "root_file"):
        return c.candidate.root_file
    return ""


def variety_shuffle(
    candidates: Iterable[T],
    *,
    key=_default_key,
) -> list[T]:
    """Round-robin interleave candidates by their key (default: file).

    Preserves the relative order of candidates sharing a key. If input
    is already score-sorted, each per-file subgroup stays score-sorted
    after the shuffle.

    Example with key=file:
        input:  [models:97, models:128, models:141, status:116, utils:457]
        output: [models:97, status:116, utils:457, models:128, models:141]
    """
    buckets: dict[str, list[T]] = defaultdict(list)
    order: list[str] = []  # first-seen order of keys
    for c in candidates:
        k = key(c)
        if k not in buckets:
            order.append(k)
        buckets[k].append(c)

    out: list[T] = []
    exhausted = False
    while not exhausted:
        exhausted = True
        for k in order:
            bucket = buckets[k]
            if bucket:
                out.append(bucket.pop(0))
                exhausted = False
    return out
