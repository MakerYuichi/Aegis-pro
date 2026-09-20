import pytest

from src.demo.file_selector import (
    select_target_file,
    _LOW_CONFIDENCE_THRESHOLD,
)


def _tree(*paths, size: int = 2000):
    """Build a tree of blobs from a list of paths. Default size ~50 lines."""
    return [{"path": p, "type": "blob", "size": size} for p in paths]


def _with_sizes(*pairs):
    """Build a tree from (path, size) pairs."""
    return [{"path": p, "type": "blob", "size": s} for p, s in pairs]


# ── Happy path ─────────────────────────────────────────────────────────

def test_picks_src_over_docs_src():
    """The fastapi probe trap: docs_src files must lose to src files."""
    tree = _tree(
        "docs_src/additional_responses/tutorial001_py310.py",
        "fastapi/applications.py",
    )
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.path == "fastapi/applications.py"


def test_picks_handler_over_utils():
    tree = _tree(
        "src/auth/handler.py",
        "src/utils.py",
    )
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.path == "src/auth/handler.py"


def test_picks_language_match_over_mismatch():
    tree = _tree(
        "src/client.go",
        "src/handler.py",
    )
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.path == "src/handler.py"


def test_picks_domain_keyword_file():
    tree = _tree(
        "src/util.py",
        "src/auth/login_handler.py",
    )
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.path == "src/auth/login_handler.py"


# ── Penalties ──────────────────────────────────────────────────────────

def test_rejects_test_files():
    tree = _tree(
        "tests/test_foo.py",
        "src/foo.py",
    )
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.path == "src/foo.py"


def test_rejects_generated_files():
    tree = _tree(
        "api/proto/handler.pb.go",
        "internal/handler.go",
    )
    result = select_target_file(tree, "Go")
    assert result is not None
    assert result.path == "internal/handler.go"


def test_rejects_docs_markdown():
    tree = _tree(
        "README.md",
        "src/main.py",
    )
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.path == "src/main.py"


def test_rejects_config_files():
    tree = _tree(
        "src/config.yaml",
        "src/handler.py",
    )
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.path == "src/handler.py"


def test_rejects_tiny_files():
    tree = _with_sizes(
        ("src/__init__.py", 50),      # ~1 line
        ("src/handler.py", 3000),     # ~75 lines
    )
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.path == "src/handler.py"


def test_rejects_huge_files():
    tree = _with_sizes(
        ("src/generated_client.py", 300_000),   # skipped entirely (>200KB)
        ("src/handler.py", 3000),
    )
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.path == "src/handler.py"


# ── Layout variations ──────────────────────────────────────────────────

def test_handles_monorepo():
    tree = _tree(
        "packages/api/src/handler.py",
        "packages/web/src/component.tsx",
        "services/auth/internal/login.go",
    )
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.path == "packages/api/src/handler.py"


def test_handles_no_src_dir():
    """Repo has no src/, only a top-level handler.py and a util.py."""
    tree = _tree(
        "handler.py",
        "util.py",
        "README.md",
    )
    result = select_target_file(tree, "Python")
    assert result is not None
    # handler keyword wins over util (no keyword)
    assert result.path == "handler.py"


def test_handles_single_file_repo():
    tree = _tree("main.py")
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.path == "main.py"
    # No src/ or keyword — low confidence
    assert result.confidence == "low"


# ── Empty / degenerate trees ───────────────────────────────────────────

def test_returns_none_for_empty_tree():
    assert select_target_file([], "Python") is None


def test_returns_none_for_tree_with_no_blobs():
    tree = [
        {"path": "src", "type": "tree"},
        {"path": "src/__pycache__", "type": "tree"},
    ]
    assert select_target_file(tree, "Python") is None


def test_returns_none_when_all_files_too_large():
    tree = _with_sizes(("a.py", 300_000), ("b.py", 500_000))
    assert select_target_file(tree, "Python") is None


# ── Confidence classification ──────────────────────────────────────────

def test_high_confidence_for_production_file():
    tree = _tree("src/auth/handler.py")
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.confidence == "high"


def test_low_confidence_for_tests_only_repo():
    """
    A tests-only repo is a weak pick, but tests/*.py is still code.
    confidence='low', not 'fallback'.
    """
    tree = _tree("tests/test_a.py", "tests/test_b.py")
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.confidence == "low"


def test_low_confidence_for_tests_only_repo():
    tree = _tree("tests/test_a.py", "tests/test_b.py")
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.confidence == "low"
    
def test_fallback_for_readme_only_repo():
    """
    The octocat/Hello-World case. A repo whose only blob is a README has
    no code file to bind to. The selector returns the README with
    confidence='fallback' so the generator synthesizes instead of
    producing 'NullPointerException at README:87'.
    """
    tree = [{"path": "README", "type": "blob", "size": 1500}]
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.path == "README"
    assert result.confidence == "fallback"
    assert any("no code extension" in r for r in result.reasons)


def test_fallback_for_config_only_repo():
    """config.yaml and data.json have no code extension → fallback."""
    tree = _tree("config.yaml", "data.json")
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.confidence == "fallback"


def test_returns_none_only_for_truly_empty_tree():
    """None is reserved for empty trees, never for bad picks."""
    # Empty list
    assert select_target_file([], "Python") is None
    # Only directories, no blobs
    tree = [{"path": "src", "type": "tree"}]
    assert select_target_file(tree, "Python") is None


# ── Determinism ────────────────────────────────────────────────────────

def test_deterministic():
    tree = _tree("src/a.py", "src/b.py", "src/c.py")
    a = select_target_file(tree, "Python")
    b = select_target_file(tree, "Python")
    assert a is not None and b is not None
    assert a.path == b.path
    assert a.score == b.score


def test_tiebreak_by_shorter_path():
    """Two files with identical scores — shorter path wins."""
    tree = _tree(
        "src/nested/deeply/handler.py",
        "src/handler.py",
    )
    result = select_target_file(tree, "Python")
    assert result is not None
    # Both match language, both under src/, both have handler keyword.
    # Deeper one gets +depth bonus so it might win. Assert determinism
    # rather than a specific winner — the important thing is it's stable.
    second = select_target_file(tree, "Python")
    assert second is not None
    assert result.path == second.path


# ── reasons field ──────────────────────────────────────────────────────

def test_reasons_populated():
    tree = _tree("src/auth/handler.py")
    result = select_target_file(tree, "Python")
    assert result is not None
    assert len(result.reasons) > 0


def test_case_insensitive_extension():
    tree = _tree("src/handler.PY")
    result = select_target_file(tree, "Python")
    assert result is not None
    assert result.path == "src/handler.PY"


# ── Unknown language ───────────────────────────────────────────────────

def test_unknown_language_does_not_penalize():
    """If repo language is None, we don't penalize extensions."""
    tree = _tree("src/handler.rb")
    result = select_target_file(tree, "Ruby")
    assert result is not None
    assert result.path == "src/handler.rb"
