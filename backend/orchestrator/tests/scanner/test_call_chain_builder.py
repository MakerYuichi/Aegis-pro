"""Tests for the call chain builder.

Uses the mini_python fixture's payment_chain/ subdirectory, which
is the three-file chain from the spec:

    payment_service.py    order = await fetch_order(order_id)
    order_service.py      return await get_by_id(order_id)
    order_repository.py   return Order(...)  or None

And the single-file #105 case:

    incident_service.py   self.rag = get_rag_service()

Also exercises the multi-branch DFS and the branch_id contract.
"""
from pathlib import Path

import pytest

from src.scanner.call_chain_builder import (
    MAX_CHAIN_FILES,
    _rollup_terminal_kind,
    build_chain,
)
from src.scanner.candidate import (
    CHAIN_NO_SYMBOL,
    CHAIN_TRACED,
    CHAIN_UNSUPPORTED_LANGUAGE,
    CHAIN_UNTRACEABLE,
    ChainLink,
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
# Three-file chain (spec's canonical case)
# ---------------------------------------------------------------------------

def test_three_file_chain_traced(repo):
    result = build_chain(
        repo_dir=repo,
        file_path="payment_chain/payment_service.py",
        line_number=11,
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
    assert result.chain[0].branch_id == 0


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
    result = build_chain(
        repo_dir=repo,
        file_path="incident_service.py",
        line_number=1,
        symbol="self.rag",
    )
    assert result.status == CHAIN_TRACED
    assert result.depth == 1
    reasons = [link.reason for link in result.chain]
    assert "assignment" in reasons
    assert result.chain[-1].reason in ("return", "assignment", "annotation")


def test_single_branch_chain_has_no_branch_ids(repo):
    """A single-source chain uses branch_id=0 throughout."""
    result = build_chain(
        repo_dir=repo,
        file_path="incident_service.py",
        line_number=1,
        symbol="self.rag",
    )
    assert result.branch_count == 0
    for link in result.chain:
        assert link.branch_id == 0


# ---------------------------------------------------------------------------
# Untraceable / unsupported
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
    assert result.status in (CHAIN_UNTRACEABLE,)


def test_missing_repo_returns_untraceable(tmp_path):
    result = build_chain(
        repo_dir=tmp_path / "nope",
        file_path="a.py",
        line_number=1,
        symbol="x",
    )
    assert result.status == CHAIN_UNTRACEABLE


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
# Multi-branch DFS (the previous "multi_source_assignment" case)
# ---------------------------------------------------------------------------

def test_multisource_assignment_produces_two_branches(tmp_path):
    """order = _cache() or _db() — the DFS visits both branches.
    Their links carry distinct branch_ids, and both call names
    appear in the chain.
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
    assert result.chain[0].reason == "usage"

    symbols = " ".join(link.symbol for link in result.chain)
    assert "_cache" in symbols
    assert "_db" in symbols


def test_multisource_branches_have_distinct_ids(tmp_path):
    """Each branch gets a distinct non-zero branch_id."""
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
    # At least two distinct non-zero branch ids.
    branch_ids = {link.branch_id for link in result.chain if link.branch_id != 0}
    assert len(branch_ids) >= 2
    # The crash site is 0.
    assert result.chain[0].branch_id == 0
    assert result.branch_count >= 2


def test_multisource_terminal_kind_is_worst_case(tmp_path):
    """If one branch is Optional and the other is Concrete, the
    rolled-up terminal_kind is Optional.
    """
    repo_dir = tmp_path / "r"
    repo_dir.mkdir()
    (repo_dir / "svc.py").write_text(
        "from typing import Optional\n"
        "\n"
        "async def get(order_id):\n"
        "    order = await _cache(order_id) or await _db(order_id)\n"
        "    return order.total\n"
        "\n"
        "async def _cache(order_id) -> Optional[dict]:\n"
        "    return None\n"
        "\n"
        "async def _db(order_id) -> dict:\n"
        "    return {}\n"
    )
    result = build_chain(
        repo_dir=repo_dir,
        file_path="svc.py",
        line_number=5,
        symbol="order",
    )
    assert result.status == CHAIN_TRACED
    # Worst-case rollup — Optional wins.
    assert result.terminal_kind == "Optional"


def test_multisource_single_branch_when_only_one_call(tmp_path):
    """order = _cache() — one branch, no multi-branch tag."""
    repo_dir = tmp_path / "r"
    repo_dir.mkdir()
    (repo_dir / "svc.py").write_text(
        "async def get(order_id):\n"
        "    order = await _cache(order_id)\n"
        "    return order.total\n"
    )
    result = build_chain(
        repo_dir=repo_dir,
        file_path="svc.py",
        line_number=3,
        symbol="order",
    )
    assert result.status == CHAIN_TRACED
    # No multi-source, so no non-zero branch_id.
    assert result.branch_count == 0


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
    assert result.status in (CHAIN_TRACED, CHAIN_UNTRACEABLE)
    assert result.depth <= MAX_CHAIN_FILES


# ---------------------------------------------------------------------------
# _rollup_terminal_kind — pure function
# ---------------------------------------------------------------------------

def test_rollup_empty_chain_is_unknown():
    assert _rollup_terminal_kind([]) == "Unknown"


def test_rollup_all_optional_is_optional():
    chain = [
        ChainLink("a.py", 1, "x", "usage", terminal_kind="Optional"),
        ChainLink("b.py", 2, "y", "return", terminal_kind="Optional"),
    ]
    assert _rollup_terminal_kind(chain) == "Optional"


def test_rollup_one_optional_wins():
    chain = [
        ChainLink("a.py", 1, "x", "usage", terminal_kind="Concrete"),
        ChainLink("b.py", 2, "y", "return", terminal_kind="Optional"),
    ]
    assert _rollup_terminal_kind(chain) == "Optional"


def test_rollup_all_concrete_is_concrete():
    chain = [
        ChainLink("a.py", 1, "x", "usage", terminal_kind="Concrete"),
        ChainLink("b.py", 2, "y", "return", terminal_kind="Concrete"),
    ]
    assert _rollup_terminal_kind(chain) == "Concrete"


def test_rollup_unknown_only_is_unknown():
    chain = [
        ChainLink("a.py", 1, "x", "usage", terminal_kind="Unknown"),
    ]
    assert _rollup_terminal_kind(chain) == "Unknown"
