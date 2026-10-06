"""Tests for the read_chain tool.

Reads every (file, line) pair in a chain in one observation,
with a cap on per-file size and on total files.
"""
from pathlib import Path

import pytest

from src.agents.tools.read_chain import (
    MAX_CHARS_PER_FILE,
    MAX_FILES,
    read_chain,
)


FIXTURE_REPO = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "repos" / "mini_python"
)


@pytest.fixture
def repo() -> str:
    assert FIXTURE_REPO.is_dir(), f"fixture missing: {FIXTURE_REPO}"
    return str(FIXTURE_REPO)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_chain_single_file(repo):
    result = await read_chain(
        repo, [{"file": "incident_service.py", "line": 30}]
    )
    assert result.ok
    assert result.tool == "read_chain"
    assert "incident_service.py" in result.result
    assert "self.rag" in result.result


@pytest.mark.asyncio
async def test_read_chain_multi_file(repo):
    result = await read_chain(
        repo,
        [
            {"file": "payment_chain/payment_service.py", "line": 11},
            {"file": "payment_chain/order_service.py", "line": 9},
        ],
    )
    assert result.ok
    assert "payment_service.py" in result.result
    assert "order_service.py" in result.result


@pytest.mark.asyncio
async def test_read_chain_sections_have_headers(repo):
    result = await read_chain(
        repo, [{"file": "incident_service.py", "line": 30}]
    )
    assert "=== incident_service.py:30" in result.result


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_chain_empty_returns_error(repo):
    result = await read_chain(repo, [])
    assert not result.ok
    assert result.error == "empty_chain"


@pytest.mark.asyncio
async def test_read_chain_missing_repo(tmp_path):
    result = await read_chain(
        str(tmp_path / "nope"), [{"file": "a.py", "line": 1}]
    )
    assert not result.ok
    assert result.error == "repo_not_found"


@pytest.mark.asyncio
async def test_read_chain_missing_file_noted_inline(repo):
    """A file that doesn't exist produces a note, not a crash."""
    result = await read_chain(
        repo, [{"file": "does_not_exist.py", "line": 1}]
    )
    # The tool succeeds if at least one section is emitted; a
    # missing file is a section with a note.
    assert result.ok
    assert "file not found" in result.result


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_chain_truncates_past_max_files(repo):
    chain = [
        {"file": "incident_service.py", "line": 1},
        {"file": "utils.py", "line": 1},
        {"file": "optional_attr_case.py", "line": 1},
        {"file": "handlers/foo.py", "line": 1},
        {"file": "payment_chain/payment_service.py", "line": 1},
        # Beyond MAX_FILES:
        {"file": "payment_chain/order_service.py", "line": 1},
        {"file": "payment_chain/order_repository.py", "line": 1},
    ]
    result = await read_chain(repo, chain)
    assert result.ok
    assert result.truncated
    assert result.metadata["files_included"] == MAX_FILES
    assert result.metadata["files_truncated"] == len(chain) - MAX_FILES
    # The truncation note names what was left out.
    assert "more files, truncated" in result.result
    assert "order_service.py" in result.result


# ---------------------------------------------------------------------------
# Context window
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_chain_uses_context_window(repo):
    """The result includes a window around the target line, not
    just the target line itself."""
    result = await read_chain(
        repo,
        [{"file": "incident_service.py", "line": 30}],
        context_lines=5,
    )
    # The header names the window.
    assert "(lines " in result.result
    # Multiple lines are present.
    assert result.result.count("\n") > 3
