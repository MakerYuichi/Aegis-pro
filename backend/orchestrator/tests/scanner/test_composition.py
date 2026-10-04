"""Composition tests for the scanner.

These tests exercise the four Phase 1 modules in sequence:
select_files → match_patterns → build_chain → score_finding. They
are the only tests that verify the modules *compose*, not just that
each behaves in isolation.

Each test documents one branch of the terminal-kind gate that
Phase 2's scan_runner will enforce:

    terminal_kind == "Optional"  → report to human
    terminal_kind == "Unknown"   → queue for scan-mode Investigator
    terminal_kind in {None, "Concrete"} → drop

The tests currently assert the *ungated* behavior — what the
modules produce today. Phase 2 will add the gate. When it does,
these tests will need updating to reflect the new contract; they
are a snapshot of the pre-Phase-2 shape, written deliberately to
make the pending change visible.

Uses the mini_python fixture, which has a self.rag case with a
known Optional terminal and a get_rag_service case with a known
Concrete terminal.
"""
from pathlib import Path

import pytest

from src.scanner.call_chain_builder import build_chain
from src.scanner.file_selector import select_files
from src.scanner.pattern_matcher import match_patterns
from src.scanner.signal_scorer import score_finding


FIXTURE_REPO = (
    Path(__file__).resolve().parents[1]
    / "fixtures" / "repos" / "mini_python"
)


@pytest.fixture
def repo() -> str:
    assert FIXTURE_REPO.is_dir(), f"fixture missing: {FIXTURE_REPO}"
    return str(FIXTURE_REPO)


# ---------------------------------------------------------------------------
# The composition itself
# ---------------------------------------------------------------------------

def test_composition_runs_all_four_modules(repo):
    """The four modules compose without adapters.

    This is the smoke test as an assertion: select_files produces
    FileScore objects, match_patterns accepts their paths, build_chain
    accepts the match's file/line/symbol, and score_finding accepts
    both. If any interface has drifted, this test fails.
    """
    repo_path = Path(repo)
    files = select_files(repo_path, top_n=5)
    assert files, "file_selector returned no files"

    produced_findings = 0
    for f in files:
        matches = match_patterns(repo_path / f.path, f.path)
        for m in matches:
            produced_findings += 1
            if m.requires_chain:
                chain = build_chain(repo, m.file, m.line, m.symbol)
                score, reason = score_finding(m, chain)
                # Score is always in range.
                assert 0.0 <= score <= 1.0
                # Reason is always a non-empty string.
                assert reason
    # The fixture has at least one pattern the matcher finds; if
    # this drops to zero, the matcher has stopped firing on the
    # fixture's known shapes.
    assert produced_findings > 0, "matcher found no patterns in fixture"


# ---------------------------------------------------------------------------
# The three gate branches
# ---------------------------------------------------------------------------

def test_composition_optional_terminal_scores_high(repo):
    """The self.rag case: the chain's terminal is Optional.

    Under Phase 2's gate this finding reaches the human report.
    Today it just scores higher than an Unknown or Concrete one.
    """
    repo_path = Path(repo)
    # Find the self.rag match in the fixture's incident_service.py.
    matches = match_patterns(repo_path / "incident_service.py",
                             "incident_service.py")
    attr_matches = [
        m for m in matches
        if m.pattern == "unchecked_optional_attr" and m.requires_chain
    ]
    assert attr_matches, (
        "fixture's incident_service.py should produce at least one "
        "unchecked_optional_attr match"
    )

    scored: list[tuple[float, str, str]] = []
    for m in attr_matches:
        chain = build_chain(repo, m.file, m.line, m.symbol)
        score, _ = score_finding(m, chain)
        scored.append((score, chain.terminal_kind or "None", m.symbol))

    # At least one finding in the fixture has an Optional terminal
    # (self.rag is assigned from get_rag_service, which returns
    # Optional["RagService"]).
    optional_findings = [
        (s, sym) for s, kind, sym in scored if kind == "Optional"
    ]
    assert optional_findings, (
        f"expected at least one Optional-terminal finding; got "
        f"{scored}"
    )

    # The Optional finding scores strictly higher than an
    # Unknown-terminal finding from the same scan (all else equal,
    # the terminal bonus is +0.15 vs -0.05).
    unknown_findings = [
        s for s, kind, _ in scored if kind == "Unknown"
    ]
    if unknown_findings:
        best_optional = max(s for s, _ in optional_findings)
        best_unknown = max(unknown_findings)
        assert best_optional > best_unknown


def test_composition_concrete_terminal_scores_low(repo):
    """A Concrete terminal produces a lower score than an Optional
    terminal with the same base confidence.

    Under Phase 2's gate, Concrete findings are dropped from the
    human report. Today they score lower than Optional ones.
    """
    # Build two synthetic matches with the same confidence and
    # chain shape, but different terminal_kind. This isolates the
    # terminal bonus from any other difference.
    from src.scanner.candidate import ChainLink, ChainResult, PatternMatch

    match = PatternMatch(
        file="a.py", line=1, symbol="x",
        pattern="unchecked_optional_attr",
        confidence="medium", requires_chain=True,
    )

    def _chain_with_kind(kind: str) -> ChainResult:
        return ChainResult(
            status="traced",
            chain=[ChainLink("a.py", 1, "x", "usage")],
            terminal_kind=kind,
        )

    optional_score, _ = score_finding(match, _chain_with_kind("Optional"))
    concrete_score, _ = score_finding(match, _chain_with_kind("Concrete"))
    assert optional_score > concrete_score


def test_composition_unknown_terminal_scores_between(repo):
    """An Unknown terminal scores strictly between Optional and
    Concrete.

    Under Phase 2's gate, Unknown findings flow into the scan-mode
    Investigator queue — not to the human report, not dropped.
    Today they score strictly below Optional and strictly above
    Concrete.
    """
    from src.scanner.candidate import ChainLink, ChainResult, PatternMatch

    match = PatternMatch(
        file="a.py", line=1, symbol="x",
        pattern="unchecked_optional_attr",
        confidence="medium", requires_chain=True,
    )

    def _chain_with_kind(kind: str) -> ChainResult:
        return ChainResult(
            status="traced",
            chain=[ChainLink("a.py", 1, "x", "usage")],
            terminal_kind=kind,
        )

    optional_score, _ = score_finding(match, _chain_with_kind("Optional"))
    unknown_score, _ = score_finding(match, _chain_with_kind("Unknown"))
    concrete_score, _ = score_finding(match, _chain_with_kind("Concrete"))

    assert optional_score > unknown_score > concrete_score
