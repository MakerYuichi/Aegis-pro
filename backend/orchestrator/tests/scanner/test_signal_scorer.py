"""Tests for the signal scorer.

The scorer is a pure function of (PatternMatch, ChainResult). All
inputs are constructed by hand — no file I/O.
"""
import pytest

from src.scanner.candidate import (
    CHAIN_TRACED,
    CHAIN_UNTRACEABLE,
    CHAIN_UNSUPPORTED_LANGUAGE,
    ChainLink,
    ChainResult,
    PatternMatch,
)
from src.scanner.signal_scorer import score_finding


def _match(confidence: str, requires_chain: bool = True) -> PatternMatch:
    return PatternMatch(
        file="a.py", line=10, symbol="order",
        pattern="unchecked_optional_attr",
        confidence=confidence,
        requires_chain=requires_chain,
    )


def _chain(depth: int, terminal_kind: str = "Optional") -> ChainResult:
    chain = [ChainLink(f"file{i}.py", i, f"s{i}", "assignment")
             for i in range(depth)]
    return ChainResult(
        status=CHAIN_TRACED,
        chain=chain,
        terminal_symbol="Order",
        terminal_kind=terminal_kind,
        reason="test",
    )


# ---------------------------------------------------------------------------
# Base scores
# ---------------------------------------------------------------------------

def test_high_confidence_higher_than_medium():
    score_hi, _ = score_finding(_match("high"), _chain(1))
    score_md, _ = score_finding(_match("medium"), _chain(1))
    assert score_hi > score_md


def test_medium_confidence_higher_than_low():
    score_md, _ = score_finding(_match("medium"), _chain(1))
    score_lo, _ = score_finding(_match("low"), _chain(1))
    assert score_md > score_lo


def test_score_clamped_to_zero_and_one():
    score, _ = score_finding(_match("high"), _chain(5, "Optional"))
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Chain bonuses
# ---------------------------------------------------------------------------

def test_multi_file_chain_scores_higher_than_single():
    single, _ = score_finding(_match("medium"), _chain(1))
    multi, _ = score_finding(_match("medium"), _chain(3))
    assert multi > single


def test_chain_bonus_saturates_at_three_files():
    three, _ = score_finding(_match("medium"), _chain(3))
    five, _ = score_finding(_match("medium"), _chain(5))
    assert three == five


# ---------------------------------------------------------------------------
# Terminal kind
# ---------------------------------------------------------------------------

def test_optional_terminal_boosts_score():
    optional, _ = score_finding(_match("medium"), _chain(2, "Optional"))
    unknown, _ = score_finding(_match("medium"), _chain(2, "Unknown"))
    assert optional > unknown


def test_concrete_terminal_penalizes_score():
    concrete, _ = score_finding(_match("medium"), _chain(2, "Concrete"))
    unknown, _ = score_finding(_match("medium"), _chain(2, "Unknown"))
    assert concrete < unknown


# ---------------------------------------------------------------------------
# Untraced chains
# ---------------------------------------------------------------------------

def test_untraced_chain_halves_base_for_chain_dependent_pattern():
    match = _match("high", requires_chain=True)
    chain = ChainResult(status=CHAIN_UNTRACEABLE)
    score, _ = score_finding(match, chain)
    # base 0.8 → halved 0.4
    assert 0.35 < score < 0.45


def test_untraced_chain_keeps_base_for_standalone_pattern():
    match = _match("high", requires_chain=False)
    chain = ChainResult(status=CHAIN_UNTRACEABLE)
    score, _ = score_finding(match, chain)
    assert 0.75 < score < 0.85


def test_unsupported_language_chain_has_clear_reason():
    match = _match("medium")
    chain = ChainResult(status=CHAIN_UNSUPPORTED_LANGUAGE)
    _, reason = score_finding(match, chain)
    assert "Python-only" in reason


# ---------------------------------------------------------------------------
# Reasoning
# ---------------------------------------------------------------------------

def test_reasoning_mentions_depth_for_multi_file():
    match = _match("medium")
    _, reason = score_finding(match, _chain(3))
    assert "3 files" in reason or "3 " in reason


def test_reasoning_mentions_single_file():
    match = _match("medium")
    _, reason = score_finding(match, _chain(1))
    assert "single-file" in reason.lower() or "1" in reason


def test_standalone_pattern_reason_says_no_chain_needed():
    match = _match("medium", requires_chain=False)
    chain = ChainResult(status=CHAIN_UNTRACEABLE)
    _, reason = score_finding(match, chain)
    assert "standalone" in reason.lower() or "no chain" in reason.lower()
