"""Dataclasses for the scanner.

[... top-of-file docstring unchanged ...]
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
        file:          repo-relative POSIX path
        line:          1-indexed line number where the symbol is
                       assigned / returned / declared
        symbol:        the symbol involved (e.g. "order", "self.rag",
                       "get_rag_service")
        reason:        one of "usage", "assignment", "return",
                       "parameter", "annotation", "definition",
                       "multi_source_assignment"
        snippet:       the source line, stripped
        terminal_kind: this link's own classification of its symbol:
                       "Optional" if the symbol or annotation can be
                       None, "Concrete" if it names a class or builtin
                       type, "Unknown" otherwise. Per-link, not
                       rolled up. ChainResult.terminal_kind carries
                       the worst-case rollup.
        branch_id:     which top-level branch this link descends from,
                       when the chain contains a multi-source
                       assignment. See below.

    branch_id contract:

        0 = no branch point. This link is either the crash site
            itself, or the first link of a single-source chain, or
            a link that precedes any `a() or b()` in the traversal.

        1, 2, 3, ... = one of the branches spawned by a multi-source
            assignment. Each branch of a single assignment gets a
            distinct, monotonically increasing id within the same
            chain. Branches are 1-indexed, never 0-indexed, so that
            0 has exactly one meaning and no consumer has to check
            "is there a branch point at all?" before interpreting
            the value.

    `0` is a sentinel, not a branch number. `groupby(chain, key=link.branch_id)`
    therefore works without any null check: the group keyed by 0 is
    always "the parts of the chain that aren't inside a branch",
    and every other key is a real branch.
    """
    file: str
    line: int
    symbol: str
    reason: str
    snippet: str = ""
    terminal_kind: str = "Unknown"
    branch_id: int = 0

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "symbol": self.symbol,
            "reason": self.reason,
            "snippet": self.snippet,
            "terminal_kind": self.terminal_kind,
            "branch_id": self.branch_id,
        }


@dataclass
class ChainResult:
    """The call_chain_builder's output for one suspicious symbol.

    Fields:
        status:          one of the CHAIN_* constants
        chain:           list[ChainLink], in DFS traversal order.
                         The first element is always the crash site.
                         Subsequent elements carry branch_id tags
                         when the traversal passed through a
                         multi-source assignment.
        terminal_symbol: the last symbol traced
        terminal_kind:   worst-case rollup across every link in the
                         chain — "Optional" if any link is Optional,
                         "Concrete" if all are Concrete, "Unknown"
                         otherwise. This is the field the scorer
                         reads. The per-link detail is on each
                         ChainLink.terminal_kind.
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
        """Number of unique files in the chain. 1 means single-file."""
        return len({link.file for link in self.chain})

    @property
    def branch_count(self) -> int:
        """Number of branches spawned by multi-source assignments.

        Counts distinct non-zero branch_ids. A chain with no branch
        point returns 0.
        """
        return len({link.branch_id for link in self.chain if link.branch_id != 0})



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
