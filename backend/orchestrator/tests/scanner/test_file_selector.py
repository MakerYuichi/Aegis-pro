"""Tests for the file selector.

Uses the mini_python fixture, which is a small Python repo with a
handful of files. The churn scoring runs against the fixture's
actual git history when available and falls back to structural
when not.
"""
import subprocess
from pathlib import Path

import pytest

from src.scanner.file_selector import (
    default_top_n,
    select_files,
    _churn_subscore,
    _complexity_subscore,
    _pattern_subscore,
    _centrality_subscore,
)


FIXTURE_REPO = (
    Path(__file__).resolve().parents[1]
    / "fixtures" / "repos" / "mini_python"
)


@pytest.fixture
def repo(tmp_path):
    """A temp copy of mini_python with its own git history.

    select_files calls git; giving each test its own repo means the
    tests aren't sensitive to the ambient working tree's state.
    """
    dest = tmp_path / "mini_python"
    import shutil
    shutil.copytree(FIXTURE_REPO, dest)
    # Fresh git repo with one commit so churn has something to see.
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.t"], cwd=dest, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=dest, check=True,
    )
    subprocess.run(["git", "add", "."], cwd=dest, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=dest, check=True,
    )
    return dest


# ---------------------------------------------------------------------------
# default_top_n
# ---------------------------------------------------------------------------

def test_default_top_n_tiers():
    assert default_top_n(50) == 10
    assert default_top_n(500) == 25
    assert default_top_n(5000) == 50
    assert default_top_n(50000) == 100


# ---------------------------------------------------------------------------
# Sub-scorers
# ---------------------------------------------------------------------------

def test_churn_subscore_zero_for_no_changes():
    score, reason = _churn_subscore(0, 30)
    assert score == 0.0
    assert reason == ""


def test_churn_subscore_saturates_at_100_lines():
    score, _ = _churn_subscore(100, 30)
    assert score == 1.0
    score_200, _ = _churn_subscore(200, 30)
    assert score_200 == 1.0


def test_churn_subscore_scales_below_saturation():
    score, reason = _churn_subscore(50, 30)
    assert 0.4 < score < 0.6
    assert "50 lines" in reason


def test_pattern_subscore_zero_for_clean_file():
    score, reasons = _pattern_subscore("x = 1\ny = 2\n")
    assert score == 0.0
    assert reasons == []


def test_pattern_subscore_counts_bare_except():
    text = """
try:
    x = 1
except:
    pass
"""
    score, reasons = _pattern_subscore(text)
    assert score > 0.0
    assert any("bare except" in r for r in reasons)


def test_pattern_subscore_ignores_regex_in_comments():
    """A comment mentioning bad code is not a pattern match."""
    text = """
# TODO: fix the `except: pass` here
x = 1
"""
    score, reasons = _pattern_subscore(text)
    assert score == 0.0


def test_complexity_subscore_scales_with_line_count():
    small = "x = 1\n"
    big = "x = 1\n" * 1000
    assert _complexity_subscore(small) < 0.01
    assert _complexity_subscore(big) == 1.0


def test_centrality_subscore_from_importer_count():
    assert _centrality_subscore(0) == 0.0
    assert _centrality_subscore(20) == 1.0
    assert 0.4 < _centrality_subscore(10) < 0.6


# ---------------------------------------------------------------------------
# select_files
# ---------------------------------------------------------------------------

def test_select_files_returns_ranked_list(repo):
    files = select_files(repo, top_n=5)
    assert len(files) <= 5
    # Sorted descending by score.
    scores = [f.score for f in files]
    assert scores == sorted(scores, reverse=True)


def test_select_files_top_n_truncates(repo):
    files = select_files(repo, top_n=2)
    assert len(files) <= 2


def test_select_files_deterministic(repo):
    first = select_files(repo, top_n=5)
    second = select_files(repo, top_n=5)
    assert [f.path for f in first] == [f.path for f in second]


def test_select_files_reasons_populated(repo):
    files = select_files(repo, top_n=5)
    # At least one file should carry a reason — the pattern matcher
    # fires on the bare_except fixture and the churn score fires on
    # the fresh commit.
    assert any(f.reasons for f in files)


def test_select_files_empty_repo_returns_empty(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert select_files(empty) == []


def test_select_files_missing_repo_returns_empty(tmp_path):
    assert select_files(tmp_path / "nope") == []


def test_select_files_no_python_files_returns_empty(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "a.txt").write_text("hi")
    assert select_files(other) == []


def test_select_files_churn_scores_nonzero_after_commit(repo):
    files = select_files(repo, top_n=100)
    # Every file was just committed, so every file should have churn
    # > 0. At least one file should have a churn reason.
    assert any(f.churn_score > 0 for f in files)


def test_select_files_since_days_zero_finds_nothing(tmp_path):
    """A since_days=0 window finds no commits and falls back."""
    import shutil
    dest = tmp_path / "r"
    shutil.copytree(FIXTURE_REPO, dest)
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=dest, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=dest, check=True)
    subprocess.run(["git", "add", "."], cwd=dest, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=dest, check=True)

    files = select_files(dest, top_n=5, since_days=0)
    # Should still return files — structural fallback.
    assert len(files) > 0
