"""
Tests for the clone-once helper. All tests run without network —
they either clone a local fixture path or assert on the failure
paths.
"""
from pathlib import Path
import shutil
import uuid

from src.agents.repo_clone import (
    _base_dir,
    cleanup_repo,
    clone_repo,
    is_local_path,
    repo_url,
)

import pytest

from src.agents.repo_clone import (
    cleanup_repo,
    clone_repo,
    is_local_path,
    repo_url,
)

FIXTURE_REPO = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "repos"
    / "mini_python"
)


def test_is_local_path_absolute():
    assert is_local_path("/tmp/foo") is True


def test_is_local_path_relative():
    assert is_local_path("./repo") is True
    assert is_local_path("../repo") is True


def test_is_local_path_github_name():
    assert is_local_path("owner/repo") is False


def test_is_local_path_empty():
    assert is_local_path("") is False


def test_repo_url_github_name():
    assert repo_url("owner/repo") == "https://github.com/owner/repo.git"


def test_repo_url_passthrough_https():
    assert repo_url("https://gitlab.com/org/repo.git") == "https://gitlab.com/org/repo.git"


@pytest.mark.asyncio
async def test_clone_repo_local_path_returns_unchanged():
    path, err = await clone_repo(str(FIXTURE_REPO))
    assert err is None
    assert path == str(FIXTURE_REPO)


@pytest.mark.asyncio
async def test_clone_repo_local_path_missing():
    path, err = await clone_repo("/tmp/definitely-not-here-xyz")
    assert path is None
    assert "local_path_not_found" in err


@pytest.mark.asyncio
async def test_clone_repo_invalid_name():
    path, err = await clone_repo("notanownerrepo")
    assert path is None
    assert "invalid_repo_name" in err


@pytest.mark.asyncio
async def test_clone_repo_empty():
    path, err = await clone_repo("")
    assert path is None
    assert "invalid_repo_name" in err


def test_cleanup_repo_none():
    # Should not raise.
    cleanup_repo(None)


def test_cleanup_repo_local_path_not_deleted():
    # A local path the caller handed us is not ours to delete.
    cleanup_repo(str(FIXTURE_REPO))
    assert FIXTURE_REPO.is_dir()

def test_cleanup_repo_removes_path_under_base_dir():
    """A path under _base_dir() is ours to delete."""
    target = _base_dir() / f"inv-test-{uuid.uuid4().hex[:12]}"
    target.mkdir(parents=True, exist_ok=True)
    (target / "marker.txt").write_text("clone")

    assert target.exists()
    cleanup_repo(str(target))
    assert not target.exists(), (
        f"cleanup_repo did not remove {target}. Contents: "
        f"{list(target.iterdir()) if target.exists() else 'N/A'}"
    )


def test_cleanup_repo_leaves_path_outside_base_dir(monkeypatch):
    """
    A path outside _base_dir() is not ours. cleanup_repo must not
    touch it.

    _base_dir is mocked to a directory the test controls, so the
    assertion is deterministic across environments. The real
    _base_dir() returns the system temp root, which pytest's
    tmp_path also lives under — so a non-mocked version of this
    test can't actually construct a path that's outside it.
    """
    import tempfile
    from src.agents import repo_clone

    # Fake "our base dir" — an empty dir the test owns.
    fake_base = Path(tempfile.mkdtemp(prefix="aegis-fake-base-"))
    monkeypatch.setattr(repo_clone, "_base_dir", lambda: fake_base)

    # A directory that is definitely NOT under fake_base.
    outside = Path(tempfile.mkdtemp(prefix="aegis-outside-"))
    try:
        (outside / "keep.txt").write_text("caller data")

        # Sanity: the test's premise must hold.
        assert not str(outside.resolve()).startswith(str(fake_base.resolve())), (
            "test setup invalid: outside path is inside fake_base"
        )

        cleanup_repo(str(outside))

        assert outside.exists(), (
            "cleanup_repo deleted a path outside base dir"
        )
        assert (outside / "keep.txt").exists()
    finally:
        import shutil
        shutil.rmtree(outside, ignore_errors=True)
        shutil.rmtree(fake_base, ignore_errors=True)
