"""Tests for the call chain builder.

Uses the mini_python fixture's payment_chain/ subdirectory, which
is the three-file chain from the spec:

    payment_service.py:14    order = await fetch_order(order_id)
    order_service.py:9       return await get_by_id(order_id)
    order_repository.py:8    return Order(...)  or None

And the single-file #105 case:

    incident_service.py      self.rag = get_rag_service()
"""
from pathlib import Path

import pytest

from src.scanner.call_chain_builder import build_chain, MAX_CHAIN_FILES
from src.scanner.candidate import (
    CHAIN_NO_SYMBOL,
    CHAIN_TRACED,
    CHAIN_UNSUPPORTED_LANGUAGE,
    CHAIN_UNTRACEABLE,
)


FIXTURE_REPO = (
    Path(__file__).resolve().parents[1]
    / "fixtures" / "repos" / "mini_python"
)


@pytest.fixture
def repo() -> str:
    assert FIXTURE_REPO.is_dir(), f"fixture missing: {FIXTURE_REPO}"
    return str(FIXTURE_REPO)


# ---------------------------------------------------------------------------
# Happy path: three-file chain
# ---------------------------------------------------------------------------

def test_three_file_chain_traced(repo):
    """The spec's canonical case — order comes from fetch_order."""
    result = build_chain(
        repo_dir=repo,
        file_path="payment_chain/payment_service.py",
        line_number=11,  # order.total
        symbol="order",
    )
    assert result.status == CHAIN_TRACED
    assert result.depth >= 2
    files = {link.file for link in result.chain}
    assert "payment_chain/payment_service.py" in files


def test_chain_front_is_the_crash_site(repo):
    result = build_chain(
        repo_dir=repo,
        file_path="payment_chain/payment_service.py",
        line_number=11,
        symbol="order",
    )
    assert result.chain[0].file == "payment_chain/payment_service.py"
    assert result.chain[0].line == 11
    assert result.chain[0].reason == "usage"


def test_chain_terminal_records_annotation_or_symbol(repo):
    result = build_chain(
        repo_dir=repo,
        file_path="payment_chain/payment_service.py",
        line_number=11,
        symbol="order",
    )
    assert result.chain[-1].symbol  # something named


def test_chain_depth_caps_at_max(repo):
    result = build_chain(
        repo_dir=repo,
        file_path="payment_chain/payment_service.py",
        line_number=11,
        symbol="order",
    )
    assert result.depth <= MAX_CHAIN_FILES


def test_chain_reason_mentions_files(repo):
    result = build_chain(
        repo_dir=repo,
        file_path="payment_chain/payment_service.py",
        line_number=11,
        symbol="order",
    )
    assert result.reason
    assert "payment_chain" in result.reason


# ---------------------------------------------------------------------------
# Single-file chain
# ---------------------------------------------------------------------------

def test_single_file_chain_self_rag(repo):
    """The #105 case — self.rag is assigned and used in the same
    file, and the assignment's RHS is a call to a function whose
    return statement is where None can originate.
    """
    result = build_chain(
        repo_dir=repo,
        file_path="incident_service.py",
        line_number=1,
        symbol="self.rag",
    )
    assert result.status == CHAIN_TRACED
    assert result.depth == 1  # all in incident_service.py
    # The chain should have found the assignment.
    reasons = [link.reason for link in result.chain]
    assert "assignment" in reasons
    # The terminal is now the return statement inside
    # get_rag_service — that's where None originates. This is the
    # chain builder doing its job: following the assignment to the
    # function whose return value is the actual null source.
    assert result.chain[-1].reason in ("return", "assignment", "annotation")


# ---------------------------------------------------------------------------
# Untraceable cases
# ---------------------------------------------------------------------------

def test_untraceable_symbol_returns_untraceable(repo):
    result = build_chain(
        repo_dir=repo,
        file_path="incident_service.py",
        line_number=1,
        symbol="never_defined_anywhere",
    )
    assert result.status == CHAIN_UNTRACEABLE
    assert result.chain == []


def test_missing_file_returns_untraceable(repo):
    result = build_chain(
        repo_dir=repo,
        file_path="does_not_exist.py",
        line_number=1,
        symbol="x",
    )
    # The trace walks the tree, finds nothing, returns untraceable.
    assert result.status in (CHAIN_UNTRACEABLE,)


def test_missing_repo_returns_untraceable(tmp_path):
    result = build_chain(
        repo_dir=tmp_path / "nope",
        file_path="a.py",
        line_number=1,
        symbol="x",
    )
    assert result.status == CHAIN_UNTRACEABLE


# ---------------------------------------------------------------------------
# Unsupported language
# ---------------------------------------------------------------------------

def test_non_python_returns_unsupported_language(repo):
    result = build_chain(
        repo_dir=repo,
        file_path="app.js",
        line_number=1,
        symbol="x",
    )
    assert result.status == CHAIN_UNSUPPORTED_LANGUAGE
    assert "Python-only" in result.reason


def test_empty_symbol_returns_no_symbol(repo):
    result = build_chain(
        repo_dir=repo,
        file_path="incident_service.py",
        line_number=1,
        symbol="",
    )
    assert result.status == CHAIN_NO_SYMBOL


def test_whitespace_symbol_returns_no_symbol(repo):
    result = build_chain(
        repo_dir=repo,
        file_path="incident_service.py",
        line_number=1,
        symbol="   ",
    )
    assert result.status == CHAIN_NO_SYMBOL


# ---------------------------------------------------------------------------
# Multi-source assignment (Q1's hard case)
# ---------------------------------------------------------------------------

def test_multisource_assignment_records_both_branches(tmp_path):
    """order = _cache() or _db() — both sources recorded in one
    multi-source link. The full per-branch DFS is a follow-up.
    """
    repo_dir = tmp_path / "r"
    repo_dir.mkdir()
    (repo_dir / "svc.py").write_text(
        "async def get(order_id):\n"
        "    order = await _cache(order_id) or await _db(order_id)\n"
        "    return order.total\n"
        "\n"
        "async def _cache(order_id):\n"
        "    return None\n"
        "\n"
        "async def _db(order_id):\n"
        "    return None\n"
    )
    result = build_chain(
        repo_dir=repo_dir,
        file_path="svc.py",
        line_number=3,
        symbol="order",
    )
    assert result.status == CHAIN_TRACED
    assert result.chain[0].line == 3
    assert result.chain[0].reason == "usage"
    assert result.chain[1].line == 2
    assert result.chain[1].reason == "multi_source_assignment"
    assert "_cache" in result.chain[1].symbol
    assert "_db" in result.chain[1].symbol


# ---------------------------------------------------------------------------
# Recursion guard
# ---------------------------------------------------------------------------

def test_recursive_assignment_does_not_loop(tmp_path):
    repo_dir = tmp_path / "r"
    repo_dir.mkdir()
    (repo_dir / "a.py").write_text(
        "def f(x):\n"
        "    x = f(x)\n"
        "    return x.bar\n"
    )
    result = build_chain(
        repo_dir=repo_dir,
        file_path="a.py",
        line_number=3,
        symbol="x",
    )
    # Should terminate one way or another — either traced with a
    # short chain, or untraceable. Neither loops.
    assert result.status in (CHAIN_TRACED, CHAIN_UNTRACEABLE)
    assert result.depth <= MAX_CHAIN_FILES
