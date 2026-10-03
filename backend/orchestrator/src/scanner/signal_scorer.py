"""Score a finding after its chain is built.

This is the *second* scorer in the pipeline. It answers a different
question from `file_selector`:

    file_selector  (Step 2)  → "which files should we look at?"
    signal_scorer  (Step 5)  → "is this finding worth surfacing?"

The two are not the same function with different arguments. They
run at different moments, on different inputs, for different
purposes.

The scoring function:

    score = base(pattern, confidence)
          + chain_bonus(depth)
          + terminal_bonus(kind)

Chain depth is the largest term because a multi-file bug is
inherently more interesting than a single-file smell. A finding
that spans three files is a logic bug; a finding that names one
line is a lint.

Base scores by confidence:
    high   → 0.8
    medium → 0.5
    low    → 0.2

Chain bonus (multiplicative-ish, additive in the total):
    depth 1 → 0.0
    depth 2 → 0.15
    depth 3+ → 0.25

Terminal kind bonus:
    Optional → 0.15  (the suspicion is confirmed by the type)
    Concrete → -0.10 (the type says it can't be None — penalize)
    Unknown  → 0.0
"""

from __future__ import annotations

from src.scanner.candidate import (
    CHAIN_TRACED,
    CHAIN_UNSUPPORTED_LANGUAGE,
    CHAIN_UNTRACEABLE,
    ChainResult,
    PatternMatch,
)


# ---------------------------------------------------------------------------
# Base scores
# ---------------------------------------------------------------------------

_CONFIDENCE_BASE: dict[str, float] = {
    "high": 0.8,
    "medium": 0.5,
    "low": 0.2,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_finding(
    match: PatternMatch, chain: ChainResult
) -> tuple[float, str]:
    """Compute a score and a one-sentence reasoning for a finding.

    Returns (score, reasoning). Score is clamped to [0.0, 1.0].

    `chain` is the ChainResult from `build_chain` for the match's
    (file, line, symbol). When the chain is untraced, only the base
    score contributes — a low-confidence suspicion with no chain
    stays low.
    """
    base = _CONFIDENCE_BASE.get(match.confidence, 0.2)

    if chain.status != CHAIN_TRACED or not chain.chain:
        # No chain. Only the base score.
        if match.requires_chain:
            # A pattern that needs a chain to be meaningful, with no
            # chain, is weak. Halve the base.
            score = base * 0.5
        else:
            # A standalone smell is still a smell.
            score = base
        score = max(0.0, min(1.0, score))
        return score, _reason_no_chain(match, chain)

    depth = chain.depth
    chain_bonus = _chain_bonus(depth)
    terminal_bonus = _terminal_bonus(chain.terminal_kind)

    score = base + chain_bonus + terminal_bonus
    score = max(0.0, min(1.0, score))

    return score, _reason_with_chain(match, chain, depth)


# ---------------------------------------------------------------------------
# Bonuses
# ---------------------------------------------------------------------------

def _chain_bonus(depth: int) -> float:
    if depth <= 1:
        return 0.0
    if depth == 2:
        return 0.15
    return 0.25


def _terminal_bonus(kind: str | None) -> float:
    if kind == "Optional":
        return 0.15
    if kind == "Concrete":
        return -0.10
    return 0.0


# ---------------------------------------------------------------------------
# Reasoning strings
# ---------------------------------------------------------------------------

def _reason_no_chain(match: PatternMatch, chain: ChainResult) -> str:
    """Reasoning for a finding whose chain didn't trace."""
    # The match's own requires_chain flag dominates. A standalone
    # smell's reason should say so regardless of chain status.
    if not match.requires_chain:
        return (
            f"{match.pattern} at {match.file}:{match.line} — "
            f"standalone smell, no chain needed."
        )
    if chain.status == CHAIN_UNSUPPORTED_LANGUAGE:
        return (
            f"{match.pattern} at {match.file}:{match.line} — chain "
            f"tracing is Python-only, so the symbol {match.symbol!r} "
            f"could not be traced. Suspicion recorded, not confirmed."
        )
    if chain.status == CHAIN_UNTRACEABLE:
        return (
            f"{match.pattern} at {match.file}:{match.line} — could "
            f"not trace {match.symbol!r} to an origin. Suspicion "
            f"recorded, not confirmed."
        )
    return (
        f"{match.pattern} at {match.file}:{match.line} — "
        f"suspicion recorded."
    )


def _reason_with_chain(
    match: PatternMatch, chain: ChainResult, depth: int
) -> str:
    """Reasoning for a finding whose chain traced."""
    files = list(dict.fromkeys(link.file for link in chain.chain))
    if depth == 1:
        return (
            f"{match.pattern} at {match.file}:{match.line} — "
            f"single-file chain, {chain.terminal_kind or 'Unknown'} "
            f"terminal at {chain.chain[-1].file}:{chain.chain[-1].line}."
        )
    file_list = " → ".join(files)
    return (
        f"{match.pattern} at {match.file}:{match.line} spans "
        f"{depth} files ({file_list}). Terminal type: "
        f"{chain.terminal_kind or 'Unknown'}."
    )
