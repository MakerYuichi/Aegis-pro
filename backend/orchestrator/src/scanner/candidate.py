"""Dataclasses for the scanner.

Four types:

    FileLocation   — a (file, line) pair. Used inside chains.
    ChainLink      — a FileLocation plus symbol/reason/snippet. One
                     link in a call chain.
    ChainResult    — the call_chain_builder's output. Status is one
                     of "traced", "untraceable", "unsupported_language",
                     "no_symbol". A "traced" result carries a chain of
                     ChainLinks.
    FileScore      — the file_selector's output. A file path plus a
                     combined score and the sub-scores that produced it.
    PatternMatch   — the pattern_matcher's output. A (file, line,
                     symbol, pattern) tuple plus a confidence.
    ScanCandidate  — the scanner's terminal output for one finding.
                     Combines a PatternMatch, a ChainResult, and a
                     score.

Design notes:

- ChainResult.status uses explicit string constants, exported so
  callers don't string-compare against typos.

- ScanCandidate is the one type that downstream stages consume. Its
  shape is stable. The other types are internal.

- FileLocation is separate from ChainLink because a bare (file, line)
  pair is a common shape (for the "root" of a chain, for a pattern
  match's location) and doesn't need the extra fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ChainResult.status values.
CHAIN_TRACED = "traced"
CHAIN_UNTRACEABLE = "untraceable"
CHAIN_UNSUPPORTED_LANGUAGE = "unsupported_language"
CHAIN_NO_SYMBOL = "no_symbol"

ALL_CHAIN_STATUSES = (
    CHAIN_TRACED,
    CHAIN_UNTRACEABLE,
    CHAIN_UNSUPPORTED_LANGUAGE,
    CHAIN_NO_SYMBOL,
)


@dataclass(frozen=True)
class FileLocation:
    """A (file, line) pair.

    `file` is repo-relative POSIX. `line` is 1-indexed.
    """
    file: str
    line: int

    def to_dict(self) -> dict:
        return {"file": self.file, "line": self.line}


@dataclass
class ChainLink:
    """One link in a call chain.

    Fields:
        file:     repo-relative POSIX path
        line:     1-indexed line number where the symbol is
                  assigned / returned / declared
        symbol:   the symbol involved (e.g. "order", "self.rag",
                  "get_rag_service")
        reason:   one of "assignment", "return", "parameter",
                  "import", "annotation"
        snippet:  the source line, stripped, for the reasoning string
    """
    file: str
    line: int
    symbol: str
    reason: str
    snippet: str = ""

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "symbol": self.symbol,
            "reason": self.reason,
            "snippet": self.snippet,
        }


@dataclass
class ChainResult:
    """The call_chain_builder's output for one suspicious symbol.

    Fields:
        status:          one of the CHAIN_* constants
        chain:           list[ChainLink], ordered from the crash site
                         to the terminal definition. Empty when
                         status is not CHAIN_TRACED.
        terminal_symbol: the last symbol traced (e.g. "Optional")
        terminal_kind:   "Optional", "Concrete", or "Unknown"
        reason:          one-sentence human-readable explanation
    """
    status: str
    chain: list[ChainLink] = field(default_factory=list)
    terminal_symbol: str | None = None
    terminal_kind: str | None = None
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "chain": [link.to_dict() for link in self.chain],
            "terminal_symbol": self.terminal_symbol,
            "terminal_kind": self.terminal_kind,
            "reason": self.reason,
        }

    @property
    def depth(self) -> int:
        """Number of files involved. 1 means single-file."""
        return len({link.file for link in self.chain})


@dataclass
class PatternMatch:
    """The pattern_matcher's output for one suspicious shape.

    Fields:
        file:        repo-relative POSIX path
        line:        1-indexed
        symbol:      the symbol the pattern involves (e.g. "order",
                     "self.rag")
        pattern:     the pattern name (e.g. "unchecked_optional_attr",
                     "unchecked_dict_access")
        confidence:  "high" | "medium" | "low" — the matcher's own
                     confidence that this is worth investigating.
                     The signal_scorer may override this.
        snippet:     the source line, stripped
        requires_chain: True when the pattern's danger depends on a
                     symbol's origin (which the matcher cannot see).
                     False for patterns that are dangerous on their
                     own (e.g. bare `except: pass`).
    """
    file: str
    line: int
    symbol: str
    pattern: str
    confidence: str
    snippet: str = ""
    requires_chain: bool = True

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "symbol": self.symbol,
            "pattern": self.pattern,
            "confidence": self.confidence,
            "snippet": self.snippet,
            "requires_chain": self.requires_chain,
        }


@dataclass
class FileScore:
    """The file_selector's output for one file.

    `score` is the combined weighted score. The sub-scores are kept
    for debugging and for the report's "why was this scanned?" line.
    """
    path: str
    score: float
    churn_score: float
    risk_pattern_score: float
    complexity_score: float
    centrality_score: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "score": self.score,
            "churn_score": self.churn_score,
            "risk_pattern_score": self.risk_pattern_score,
            "complexity_score": self.complexity_score,
            "centrality_score": self.centrality_score,
            "reasons": self.reasons,
        }


@dataclass
class ScanCandidate:
    """The scanner's terminal output for one finding.

    Combines a PatternMatch with its ChainResult and a finding score.
    This is what downstream stages (Phase 2's scan_runner) consume.

    Fields:
        root_file, root_line, symbol: from the PatternMatch
        pattern:                      from the PatternMatch
        chain:                        from the ChainResult (may be empty)
        chain_status:                 from the ChainResult
        chain_depth:                  number of files in the chain
        score:                        from signal_scorer
        reasoning:                    one-sentence human-readable why
        metadata:                     matcher/scorer-specific extras
    """
    root_file: str
    root_line: int
    symbol: str
    pattern: str
    chain: list[ChainLink] = field(default_factory=list)
    chain_status: str = CHAIN_UNTRACEABLE
    chain_depth: int = 0
    score: float = 0.0
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "root_file": self.root_file,
            "root_line": self.root_line,
            "symbol": self.symbol,
            "pattern": self.pattern,
            "chain": [link.to_dict() for link in self.chain],
            "chain_status": self.chain_status,
            "chain_depth": self.chain_depth,
            "score": self.score,
            "reasoning": self.reasoning,
            "metadata": self.metadata,
        }
