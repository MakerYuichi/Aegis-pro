"""Scanner — proactive multi-file code analysis (v1.0 Phase 1).

The scanner finds latent bugs in a repository *without* a stack trace.
It ranks files, matches suspicious patterns, traces symbols across
file boundaries, and scores the results.

Scope: Python-only, explicitly. The chain builder needs Python's
`ast` module to trace a symbol's origin across files. Non-Python
files are not skipped silently — `call_chain_builder` returns
status="unsupported_language" and the caller surfaces that honestly.

Phase 1 scope (this module):
    candidate.py          — dataclasses
    file_selector.py      — pick the top-N files to scan
    pattern_matcher.py    — find suspicious shapes in a file
    call_chain_builder.py — trace a symbol to its origin across files
    signal_scorer.py      — score a finding after a chain is built

Phase 1 does NOT include:
    - scan_runner.py (Phase 2)
    - the scanner stage in incident_service (Phase 2)
    - the read_chain tool (Phase 2)
"""

from src.scanner.candidate import (
    ChainLink,
    ChainResult,
    FileLocation,
    FileScore,
    ScanCandidate,
)
from src.scanner.file_selector import select_files, default_top_n
from src.scanner.pattern_matcher import PatternMatch, match_patterns
from src.scanner.call_chain_builder import build_chain
from src.scanner.signal_scorer import score_finding

__all__ = [
    # Dataclasses
    "ChainLink",
    "ChainResult",
    "FileLocation",
    "FileScore",
    "ScanCandidate",
    # Functions
    "select_files",
    "default_top_n",
    "match_patterns",
    "build_chain",
    "score_finding",
]
