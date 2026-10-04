"""Tests for the signal scorer.

The scorer is a pure function of (PatternMatch, ChainResult) plus
two optional keyword arguments (blame, coverage_proxy). All inputs
are constructed by hand — no file I/O.
"""
from datetime import datetime, timedelta, timezone

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
# Blame bonus
# ---------------------------------------------------------------------------

def test_recent_blame_boosts_score():
    """A line touched last week scores higher than the same line
    with no blame signal."""
    match = _match("medium")
    chain = _chain(2)
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    with_blame, _ = score_finding(
        match, chain, blame={"timestamp": recent_ts, "author": "a"}
    )
    without_blame, _ = score_finding(match, chain)
    assert with_blame > without_blame


def test_old_blame_penalizes_score():
    """A line untouched for a year scores lower."""
    match = _match("medium")
    chain = _chain(2)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    with_blame, _ = score_finding(
        match, chain, blame={"timestamp": old_ts, "author": "a"}
    )
    without_blame, _ = score_finding(match, chain)
    assert with_blame < without_blame


def test_blame_none_contributes_zero():
    match = _match("medium")
    chain = _chain(2)
    with_none, _ = score_finding(match, chain, blame=None)
    without_arg, _ = score_finding(match, chain)
    assert with_none == without_arg


def test_blame_missing_timestamp_contributes_zero():
    match = _match("medium")
    chain = _chain(2)
    no_ts, _ = score_finding(match, chain, blame={"author": "a"})
    without_arg, _ = score_finding(match, chain)
    assert no_ts == without_arg


def test_blame_accepts_datetime_object():
    match = _match("medium")
    chain = _chain(2)
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    with_dt, _ = score_finding(match, chain, blame={"timestamp": recent})
    without_arg, _ = score_finding(match, chain)
    assert with_dt > without_arg


def test_blame_naive_datetime_treated_as_utc():
    """A timezone-naive datetime is treated as UTC."""
    match = _match("medium")
    chain = _chain(2)
    naive_recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    with_naive, _ = score_finding(
        match, chain, blame={"timestamp": naive_recent}
    )
    without_arg, _ = score_finding(match, chain)
    assert with_naive > without_arg


def test_blame_bad_timestamp_contributes_zero():
    match = _match("medium")
    chain = _chain(2)
    bad, _ = score_finding(
        match, chain, blame={"timestamp": "not a date"}
    )
    without_arg, _ = score_finding(match, chain)
    assert bad == without_arg


def test_blame_trailing_z_parses():
    """A timestamp ending in Z parses as UTC."""
    match = _match("medium")
    chain = _chain(2)
    recent_z = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    with_z, _ = score_finding(match, chain, blame={"timestamp": recent_z})
    without_arg, _ = score_finding(match, chain)
    assert with_z > without_arg


# ---------------------------------------------------------------------------
# Coverage proxy bonus
# ---------------------------------------------------------------------------

def test_coverage_proxy_true_penalizes_score():
    match = _match("medium")
    chain = _chain(2)
    tested, _ = score_finding(match, chain, coverage_proxy=True)
    without, _ = score_finding(match, chain)
    assert tested < without


def test_coverage_proxy_false_boosts_score():
    match = _match("medium")
    chain = _chain(2)
    untested, _ = score_finding(match, chain, coverage_proxy=False)
    without, _ = score_finding(match, chain)
    assert untested > without


def test_coverage_proxy_none_contributes_zero():
    match = _match("medium")
    chain = _chain(2)
    with_none, _ = score_finding(match, chain, coverage_proxy=None)
    without_arg, _ = score_finding(match, chain)
    assert with_none == without_arg


def test_coverage_proxy_applies_to_untraced_chain():
    """The signal contributes even when the chain didn't trace."""
    match = _match("medium", requires_chain=False)
    chain = ChainResult(status=CHAIN_UNTRACEABLE)
    tested, _ = score_finding(match, chain, coverage_proxy=True)
    without, _ = score_finding(match, chain)
    assert tested < without


# ---------------------------------------------------------------------------
# Combined signals
# ---------------------------------------------------------------------------

def test_recent_and_untested_scores_higher_than_old_and_tested():
    """Both signals in the danger direction beats both in the
    safety direction."""
    match = _match("medium")
    chain = _chain(2)
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()

    dangerous, _ = score_finding(
        match, chain,
        blame={"timestamp": recent_ts},
        coverage_proxy=False,
    )
    safe, _ = score_finding(
        match, chain,
        blame={"timestamp": old_ts},
        coverage_proxy=True,
    )
    assert dangerous > safe


def test_score_clamped_with_all_positive_signals():
    """Even with every bonus in the danger direction, the score is
    clamped to 1.0."""
    match = _match("high")
    chain = _chain(5, "Optional")
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    score, _ = score_finding(
        match, chain,
        blame={"timestamp": recent_ts},
        coverage_proxy=False,
    )
    assert score <= 1.0


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


def test_reasoning_includes_recent_blame_note():
    match = _match("medium")
    chain = _chain(2)
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    _, reason = score_finding(
        match, chain, blame={"timestamp": recent_ts}
    )
    assert "recently touched" in reason


def test_reasoning_includes_old_blame_note():
    match = _match("medium")
    chain = _chain(2)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    _, reason = score_finding(
        match, chain, blame={"timestamp": old_ts}
    )
    assert "stable" in reason


def test_reasoning_includes_tested_note():
    match = _match("medium")
    chain = _chain(2)
    _, reason = score_finding(match, chain, coverage_proxy=True)
    assert "test" in reason.lower()


def test_reasoning_includes_untested_note():
    match = _match("medium")
    chain = _chain(2)
    _, reason = score_finding(match, chain, coverage_proxy=False)
    assert "no test reference" in reason.lower()


def test_reasoning_has_no_suffix_when_no_signals():
    """A call with neither signal produces the old reasoning."""
    match = _match("medium")
    chain = _chain(2)
    _, reason = score_finding(match, chain)
    assert "recently" not in reason
    assert "stable" not in reason
    assert "test" not in reason.lower() or "test" in chain.reason


def test_reasoning_mentions_branch_count_when_branched():
    """A chain with branches gets a branch-count note."""
    match = _match("medium")
    chain = ChainResult(
        status=CHAIN_TRACED,
        chain=[
            ChainLink("a.py", 1, "order", "usage", branch_id=0),
            ChainLink("b.py", 2, "_cache", "return", branch_id=1),
            ChainLink("c.py", 3, "_db", "return", branch_id=2),
        ],
        terminal_kind="Optional",
        reason="test",
    )
    _, reason = score_finding(match, chain)
    assert "2 branches" in reason
