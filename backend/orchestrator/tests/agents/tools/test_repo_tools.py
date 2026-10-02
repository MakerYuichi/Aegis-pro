"""
Tests for the deterministic tool layer. No LLM, no network, no
GitHub. Every test runs against tests/fixtures/repos/mini_python.
"""
from pathlib import Path

import pytest

from src.agents.tools.repo_tools import (
    MAX_FILE_CHARS,
    MAX_MATCHES,
    MAX_SYMBOL_LINES,
    read_file,
    read_symbol,
    search_codebase,
)

FIXTURE_REPO = Path(__file__).resolve().parents[2] / "fixtures" / "repos" / "mini_python"


@pytest.fixture
def repo() -> str:
    assert FIXTURE_REPO.is_dir(), f"fixture repo missing: {FIXTURE_REPO}"
    return str(FIXTURE_REPO)


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_file_whole_file_numbers_lines(repo):
    r = await read_file(repo, "utils.py")
    assert r.ok
    assert not r.truncated
    assert r.tool == "read_file"
    assert "CONSTANT = 42" in r.result
    assert "def helper" in r.result
    # Numbered lines: the first line should carry its line number
    # before the content. Format is f"{n:5d}  {content}".
    first = r.result.splitlines()[0]
    assert first.startswith("    1  "), repr(first)
    assert first.endswith("CONSTANT = 42")


@pytest.mark.asyncio
async def test_read_file_slice_inclusive(repo):
    # utils.py line 1 is "CONSTANT = 42"; line 2 is blank; line 3 is blank.
    # Use a slice we know contains content, not blanks.
    r = await read_file(repo, "utils.py", start_line=1, end_line=2)
    assert r.ok
    lines = r.result.splitlines()
    assert len(lines) == 2
    assert "CONSTANT = 42" in lines[0]
    # Line 2 is blank — the numbered output should still be present
    # (the line number, then no content). This catches off-by-one
    # errors in the window arithmetic.
    assert lines[1].strip() == "2"


@pytest.mark.asyncio
async def test_read_file_missing(repo):
    r = await read_file(repo, "nope.py")
    assert not r.ok
    assert "not_a_file" in r.error


@pytest.mark.asyncio
async def test_read_file_rejects_traversal(repo):
    r = await read_file(repo, "../../../etc/passwd")
    assert not r.ok
    assert r.error == "path_escapes_repo"


@pytest.mark.asyncio
async def test_read_file_rejects_absolute(repo):
    r = await read_file(repo, "/etc/passwd")
    assert not r.ok
    assert r.error == "absolute_path_rejected"


@pytest.mark.asyncio
async def test_read_file_start_beyond_eof(repo):
    r = await read_file(repo, "utils.py", start_line=9999)
    assert not r.ok
    assert "exceeds file length" in r.error


@pytest.mark.asyncio
async def test_read_file_truncates_large_file(tmp_path):
    # Build a repo with a file larger than MAX_FILE_CHARS.
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    big = repo_dir / "big.py"
    big.write_text("x = 1\n" * 20_000)

    r = await read_file(str(repo_dir), "big.py")
    assert r.ok
    assert r.truncated
    assert len(r.result) <= MAX_FILE_CHARS


@pytest.mark.asyncio
async def test_read_file_repo_not_found(tmp_path):
    r = await read_file(str(tmp_path / "nope"), "any.py")
    assert not r.ok
    assert r.error == "repo_not_found"


# ---------------------------------------------------------------------------
# read_symbol — Python (the #105 case)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_symbol_finds_self_rag_assignment(repo):
    """
    The #105 case. self.rag is assigned in __init__ from
    get_rag_service(), which can return None. read_symbol must
    return the assignment line, not the method call at the failing
    line.
    """
    r = await read_symbol(repo, "incident_service.py", "self.rag")
    assert r.ok
    assert "self.rag = get_rag_service()" in r.result
    assert r.metadata["resolver"] == "python_ast"
    assert r.metadata["kind"] in ("assign_member",)


@pytest.mark.asyncio
async def test_read_symbol_finds_function_def(repo):
    r = await read_symbol(repo, "incident_service.py", "get_rag_service")
    assert r.ok
    assert "def get_rag_service" in r.result
    assert r.metadata["kind"] == "def"


@pytest.mark.asyncio
async def test_read_symbol_finds_class_def(repo):
    r = await read_symbol(repo, "incident_service.py", "IncidentService")
    assert r.ok
    assert "class IncidentService" in r.result
    assert r.metadata["kind"] == "class"


@pytest.mark.asyncio
async def test_read_symbol_finds_module_constant(repo):
    r = await read_symbol(repo, "utils.py", "CONSTANT")
    assert r.ok
    assert "CONSTANT = 42" in r.result
    assert r.metadata["kind"] in ("assign", "annassign")


@pytest.mark.asyncio
async def test_read_symbol_symbol_not_found(repo):
    r = await read_symbol(repo, "utils.py", "nonexistent_symbol")
    assert not r.ok
    assert "symbol_not_found" in r.error


@pytest.mark.asyncio
async def test_read_symbol_syntax_error(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "broken.py").write_text("def (:\n    pass\n")
    r = await read_symbol(str(repo_dir), "broken.py", "anything")
    assert not r.ok
    assert "syntax_error" in r.error


@pytest.mark.asyncio
async def test_read_symbol_caps_long_class(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    body = "class Huge:\n" + "".join(f"    x{i} = {i}\n" for i in range(200))
    (repo_dir / "big.py").write_text(body)

    r = await read_symbol(str(repo_dir), "big.py", "Huge")
    assert r.ok
    assert r.truncated
    assert r.metadata["end_line"] - r.metadata["start_line"] + 1 <= MAX_SYMBOL_LINES


@pytest.mark.asyncio
async def test_read_symbol_all_matches_metadata(repo):
    """
    When a symbol appears in multiple places (e.g. get_rag_service as
    both an import and a def), the metadata lists the first few
    matches so the agent can reason about which one it got.
    """
    r = await read_symbol(repo, "incident_service.py", "get_rag_service")
    assert r.ok
    assert "all_matches" in r.metadata
    assert isinstance(r.metadata["all_matches"], list)


# ---------------------------------------------------------------------------
# read_symbol — heuristic (non-Python)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_symbol_heuristic_javascript(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "app.js").write_text(
        "const express = require('express');\n"
        "function handler(req, res) {\n"
        "  res.send('ok');\n"
        "}\n"
    )
    r = await read_symbol(str(repo_dir), "app.js", "handler")
    assert r.ok
    assert "function handler" in r.result
    assert r.metadata["resolver"] == "heuristic"
    assert r.metadata["best_effort"] is True


@pytest.mark.asyncio
async def test_read_symbol_heuristic_go(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.go").write_text(
        "package main\n\nfunc main() {\n\tprintln(\"hi\")\n}\n"
    )
    r = await read_symbol(str(repo_dir), "main.go", "main")
    assert r.ok
    assert "func main" in r.result


@pytest.mark.asyncio
async def test_read_symbol_heuristic_unsupported_language(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "script.rb").write_text("def hello\nend\n")
    r = await read_symbol(str(repo_dir), "script.rb", "hello")
    assert not r.ok
    assert "unsupported_language" in r.error


# ---------------------------------------------------------------------------
# search_codebase
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_codebase_finds_pattern(repo):
    r = await search_codebase(repo, r"get_rag_service")
    assert r.ok
    assert "incident_service.py" in r.result
    assert r.metadata["match_count"] >= 1


@pytest.mark.asyncio
async def test_search_codebase_glob_filters(repo):
    r = await search_codebase(repo, r"def ", file_glob="**/*.py")
    assert r.ok
    assert r.metadata["match_count"] >= 1


@pytest.mark.asyncio
async def test_search_codebase_no_matches_is_ok(repo):
    r = await search_codebase(repo, r"zzz_never_matches_zzz")
    assert r.ok
    assert r.result == ""
    assert r.metadata["match_count"] == 0


@pytest.mark.asyncio
async def test_search_codebase_invalid_regex(repo):
    r = await search_codebase(repo, r"[unclosed")
    assert not r.ok
    assert "invalid_regex" in r.error


@pytest.mark.asyncio
async def test_search_codebase_empty_pattern(repo):
    r = await search_codebase(repo, "")
    assert not r.ok
    assert r.error == "empty_pattern"


@pytest.mark.asyncio
async def test_search_codebase_skips_node_modules(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text("needle = 1\n")
    nm = repo_dir / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("needle = 2\n")

    r = await search_codebase(str(repo_dir), "needle")
    assert r.ok
    assert "node_modules" not in r.result
    assert r.metadata["match_count"] == 1


@pytest.mark.asyncio
async def test_search_codebase_caps_matches(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    for i in range(200):
        (repo_dir / f"f{i}.py").write_text("needle\n")

    r = await search_codebase(str(repo_dir), "needle")
    assert r.ok
    assert r.truncated
    assert r.metadata["match_count"] == MAX_MATCHES


@pytest.mark.asyncio
async def test_search_codebase_repo_not_found(tmp_path):
    r = await search_codebase(str(tmp_path / "nope"), "anything")
    assert not r.ok
    assert r.error == "repo_not_found"


# ---------------------------------------------------------------------------
# ToolResult serialization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_result_to_observation_shape(repo):
    r = await read_file(repo, "utils.py")
    obs = r.to_observation(iteration=2)
    assert obs["iteration"] == 2
    assert obs["tool"] == "read_file"
    assert obs["ok"] is True
    assert obs["args"]["path"] == "utils.py"
    assert isinstance(obs["result"], str)


@pytest.mark.asyncio
async def test_search_codebase_recursive_glob(repo):
    """
    ** must match across path separators, not just one segment.
    Regression test for the glob semantics that fnmatch got wrong.
    """
    r = await search_codebase(repo, r"def ", file_glob="**/*.py")
    assert r.ok
    assert r.metadata["match_count"] >= 1


@pytest.mark.asyncio
async def test_search_codebase_deep_glob_matches_direct_child(repo):
    """
    The case the agent hit: a file directly under the glob's
    directory, not in a subdirectory.
    """
    r = await search_codebase(
        repo, r"get_rag_service",
        file_glob="**/*.py",
    )
    assert r.ok
    # incident_service.py is at the repo root of the fixture.
    assert r.metadata["match_count"] >= 1