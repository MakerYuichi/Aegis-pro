"""
Integration tests for the verifier's prefetch wiring.

These tests mock `run_prefetch` and `run_prefetch_with_build_on_miss`
so no network or Docker is needed. They exercise:

  - manifest discovery → prefetch call
  - no manifest → prefetch skipped, verifier still runs
  - prefetch failure → VerificationResult with prefetch_failed_* reason
  - BUILD_ON_MISS_ENABLED=false → run_prefetch instead of the
    with-build version
  - the cache mount and install command reach _run_in_docker

The verifier's own Docker behavior is tested elsewhere
(test_verifier_hosted.py). These tests only exercise the new
prefetch wiring.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.prefetch.runner import PrefetchError, PrefetchResult
from src.agents.prefetch.receipt import PrefetchReceipt
from src.agents.verifier import HostedVerifier, _run_in_docker


# ── fixtures ───────────────────────────────────────────────────

@pytest.fixture
def mock_prefetch_result(tmp_path):
    """A PrefetchResult that looks like a successful prefetch."""
    receipt = PrefetchReceipt(
        manifest_path="requirements.txt",
        manifest_hash="sha256:" + "a" * 64,
        python_version="3.11.16",
        platform_tag="linux_aarch64",
        packages=[],
        fetched_now=True,
        duration_ms=100,
    )
    return PrefetchResult(
        cache_container_path=tmp_path / "cache",
        cache_host_path=tmp_path / "cache",
        lock_path=tmp_path / "cache" / "requirements.lock",
        receipt=receipt,
    )


@pytest.fixture
def fake_repo(tmp_path):
    """
    A fake repo with a requirements.txt at root, a pyproject.toml
    with pytest config, and a tests/ directory with one test.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("fastapi==0.115.11\n")
    (repo / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n"
    )
    (repo / "app.py").write_text("x = 1\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_smoke.py").write_text("def test_ok(): pass\n")
    return repo


# ── manifest discovery ────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_manifest_skips_prefetch(fake_repo, tmp_path):
    """A repo with no dependency manifest runs tests without
    prefetch. VerificationResult is produced; prefetch wasn't
    called."""
    # Remove the manifest.
    (fake_repo / "requirements.txt").unlink()

    with patch(
        "src.agents.verifier.find_manifest", return_value=None,
    ), patch(
        "src.agents.verifier.run_prefetch_with_build_on_miss",
        new=AsyncMock(),
    ) as mock_prefetch, patch.object(
        HostedVerifier, "_apply_diff",
        new=AsyncMock(return_value=(True, "")),
    ), patch(
        "src.agents.verifier._run_in_docker",
        new=AsyncMock(return_value=(0, "1 passed")),
    ) as mock_docker:
        v = HostedVerifier()
        result = await v.verify(
            repo_name="owner/repo",
            commit_sha="HEAD",
            diff="",
            language="Python",
            context={"repo_workdir": str(tmp_path)},
        )
        mock_prefetch.assert_not_called()
            # Two docker calls now: baseline + with-diff. Both
            # run without a cache mount because there was no
            # manifest to prefetch.
        assert mock_docker.await_count == 2
        for call in mock_docker.await_args_list:
            assert call.kwargs["cache_host_path"] is None


@pytest.mark.asyncio
async def test_prefetch_error_in_context_verifies_without_cache(fake_repo, tmp_path):
    """When _stage_prefetch failed upstream, context carries prefetch_error.

    verify() does not read prefetch_error — it looks for
    prefetch_cache_host_path in the context and finds none. Tests
    run without the cache mount or install prefix. A
    VerificationResult is produced; no exception is raised.

    This documents the honest degradation: a prefetch failure is
    not a verification failure. Verification still happens, just
    without the repo's installed dependencies. The repo's tests may
    fail on import errors, and that failure is reported as
    tests_failed / tests_could_not_run, not as a prefetch error.

    Replaces the removed test_prefetch_failure_is_verification_failure,
    which asserted a reason="prefetch_failed_*" outcome that no
    longer exists. The prefetcher itself is tested separately in
    test_prefetch_*.py; verify()'s job is to consume whatever cache
    context provides, or run without one.
    """
    with patch.object(
        HostedVerifier, "_apply_diff",
        new=AsyncMock(return_value=(True, "")),
    ), patch(
        "src.agents.verifier._run_in_docker",
        new=AsyncMock(return_value=(0, "1 passed")),
    ) as mock_docker:
        v = HostedVerifier()
        result = await v.verify(
            repo_name="owner/repo",
            commit_sha="HEAD",
            diff="",
            language="Python",
            context={
                "repo_workdir": str(tmp_path),
                "prefetch_error": "sdist_only: package=sentence-transformers",
            },
        )

    # Verification ran; it didn't raise or short-circuit.
    assert result.passed is True
    assert result.reason == "tests_passed"

    # Two docker calls (baseline + with-diff), both without cache.
    assert mock_docker.await_count == 2
    for call in mock_docker.await_args_list:
        assert call.kwargs["cache_host_path"] is None
        assert call.kwargs["manifest_relative_path"] is None


# ── _run_in_docker's cache mount ──────────────────────────────

@pytest.mark.asyncio
async def test_run_in_docker_prepends_install_when_cache_provided(tmp_path):
    """When a cache is provided, the command becomes pip install
    --no-index --find-links /cache ... && <original>."""
    captured = {}

    async def fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", None))
        return proc

    with patch(
        "asyncio.create_subprocess_exec", fake_exec,
    ):
        await _run_in_docker(
            image="aegis-verifier:latest",
            host_workdir=tmp_path,
            container_workdir="/verifier-workdir",
            command="python -m pytest -q",
            timeout=60,
            memory_limit="1g",
            cpu_limit="1",
            cache_host_path=tmp_path / "cache",
            manifest_relative_path="requirements.txt",
        )

    argv = list(captured["argv"])
    # -v mount for the cache exists.
    assert any(":/cache:ro" in a for a in argv)
    # The sh -c command has the install prepended.
    sh_c_idx = argv.index("sh")
    assert argv[sh_c_idx + 1] == "-c"
    effective = argv[sh_c_idx + 2]
    assert "pip install --no-index" in effective
    assert "--find-links /cache" in effective
    # The install reads from the lock file in the cache, not from
    # the repo's manifest. The prefetcher writes the resolved lock
    # to <cache>/requirements.lock; the container installs from
    # that lock. The old assertion (`-r requirements.txt`) predates
    # the lock-file split and would only pass if the install read
    # the repo's manifest directly — which is exactly the thing
    # the prefetch design avoids (the manifest may be unpinned,
    # and pip install with network is what we're preventing).
    assert "-r /cache/requirements.lock" in effective
    assert effective.endswith("python -m pytest -q")


@pytest.mark.asyncio
async def test_run_in_docker_no_install_when_cache_missing(tmp_path):
    """No cache, no install prefix. Command runs as-is."""
    captured = {}

    async def fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", None))
        return proc

    with patch(
        "asyncio.create_subprocess_exec", fake_exec,
    ):
        await _run_in_docker(
            image="aegis-verifier:latest",
            host_workdir=tmp_path,
            container_workdir="/verifier-workdir",
            command="python -m pytest -q",
            timeout=60,
            memory_limit="1g",
            cpu_limit="1",
        )

    argv = list(captured["argv"])
    assert not any(":/cache" in a for a in argv)
    sh_c_idx = argv.index("sh")
    assert argv[sh_c_idx + 2] == "python -m pytest -q"
