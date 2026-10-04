"""Tests for scanner dataclasses."""
from src.scanner.candidate import (
    ChainLink,
    ChainResult,
    FileLocation,
    FileScore,
    PatternMatch,
    ScanCandidate,
    CHAIN_TRACED,
    CHAIN_UNTRACEABLE,
)


def test_file_location_is_hashable_and_frozen():
    a = FileLocation(file="a.py", line=1)
    b = FileLocation(file="a.py", line=1)
    assert a == b
    assert hash(a) == hash(b)
    assert {a, b} == {a}


def test_chain_link_to_dict_roundtrip():
    link = ChainLink(
        file="a.py", line=10, symbol="order",
        reason="assignment", snippet="order = fetch()",
    )
    d = link.to_dict()
    assert d == {
        "file": "a.py", "line": 10, "symbol": "order",
        "reason": "assignment", "snippet": "order = fetch()",
        "terminal_kind": "Unknown",
        "branch_id": 0,
    }
    
    
def test_chain_link_to_dict_includes_terminal_kind():
    link = ChainLink(
        file="a.py", line=10, symbol="Order",
        reason="return", terminal_kind="Concrete",
    )
    d = link.to_dict()
    assert d["terminal_kind"] == "Concrete"


def test_chain_link_to_dict_includes_branch_id():
    link = ChainLink(
        file="a.py", line=10, symbol="order",
        reason="assignment", branch_id=2,
    )
    d = link.to_dict()
    assert d["branch_id"] == 2


def test_chain_link_defaults_branch_id_to_zero():
    """branch_id defaults to 0, the sentinel for 'no branch point'."""
    link = ChainLink(file="a.py", line=1, symbol="x", reason="usage")
    assert link.branch_id == 0


def test_chain_link_defaults_terminal_kind_to_unknown():
    link = ChainLink(file="a.py", line=1, symbol="x", reason="usage")
    assert link.terminal_kind == "Unknown"



def test_chain_result_depth_counts_unique_files():
    result = ChainResult(
        status=CHAIN_TRACED,
        chain=[
            ChainLink("a.py", 1, "x", "usage"),
            ChainLink("b.py", 5, "y", "assignment"),
            ChainLink("c.py", 10, "z", "assignment"),
        ],
    )
    assert result.depth == 3


def test_chain_result_depth_ignores_duplicate_files():
    result = ChainResult(
        status=CHAIN_TRACED,
        chain=[
            ChainLink("a.py", 1, "x", "usage"),
            ChainLink("a.py", 5, "y", "assignment"),
        ],
    )
    assert result.depth == 1


def test_scan_candidate_to_dict_shape():
    c = ScanCandidate(
        root_file="a.py", root_line=10, symbol="order",
        pattern="unchecked_optional_attr",
        chain=[ChainLink("a.py", 10, "order", "usage")],
        chain_status=CHAIN_TRACED,
        chain_depth=1,
        score=0.45,
        reasoning="test",
    )
    d = c.to_dict()
    assert d["root_file"] == "a.py"
    assert d["chain_depth"] == 1
    assert d["score"] == 0.45
    assert len(d["chain"]) == 1


def test_pattern_match_to_dict_shape():
    m = PatternMatch(
        file="a.py", line=1, symbol="order",
        pattern="unchecked_optional_attr",
        confidence="low", requires_chain=True,
    )
    d = m.to_dict()
    assert d["pattern"] == "unchecked_optional_attr"
    assert d["requires_chain"] is True


def test_file_score_to_dict_includes_sub_scores():
    f = FileScore(
        path="a.py", score=1.0,
        churn_score=0.5, risk_pattern_score=0.2,
        complexity_score=0.1, centrality_score=0.05,
        reasons=["test"],
    )
    d = f.to_dict()
    assert d["churn_score"] == 0.5
    assert d["reasons"] == ["test"]


def test_chain_result_untraced_has_no_chain():
    result = ChainResult(status=CHAIN_UNTRACEABLE, reason="not found")
    assert result.chain == []
    assert result.depth == 0
