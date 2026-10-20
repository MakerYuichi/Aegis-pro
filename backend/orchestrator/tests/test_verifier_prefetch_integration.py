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
        # The docker call happens with no cache mount.
        assert mock_docker.await_count == 1
        call_kwargs = mock_docker.await_args.kwargs
        assert call_kwargs["cache_host_path"] is None


@pytest.mark.asyncio
async def test_manifest_triggers_prefetch(
    fake_repo, tmp_path, mock_prefetch_result,
):
    """A repo with requirements.txt calls the prefetcher."""
    with patch(
        "src.agents.verifier.find_manifest",
    ) as mock_find, patch(
        "src.agents.verifier.run_prefetch_with_build_on_miss",
        new=AsyncMock(return_value=mock_prefetch_result),
    ) as mock_prefetch, patch.object(
        HostedVerifier, "_apply_diff",
        new=AsyncMock(return_value=(True, "")),
    ), patch(
        "src.agents.verifier._run_in_docker",
        new=AsyncMock(return_value=(0, "1 passed")),
    ) as mock_docker:
        # Return a real ManifestRef.
        from src.agents.prefetch.manifest_finder import ManifestRef
        mock_find.return_value = ManifestRef(
            path=Path("requirements.txt"), kind="requirements",
        )

        v = HostedVerifier()
        await v.verify(
            repo_name="owner/repo",
            commit_sha="HEAD",
            diff="",
            language="Python",
            context={"repo_workdir": str(tmp_path)},
        )

        mock_prefetch.assert_awaited_once()
        # The cache mount reaches the docker call.
        call_kwargs = mock_docker.await_args.kwargs
        assert call_kwargs["cache_host_path"] is not None
        assert call_kwargs["manifest_relative_path"] == "requirements.txt"


@pytest.mark.asyncio
async def test_prefetch_failure_is_verification_failure(fake_repo, tmp_path):
    """A prefetch failure produces VerificationResult with
    prefetch_failed_* reason, not an exception."""
    with patch(
        "src.agents.verifier.find_manifest",
    ) as mock_find, patch(
        "src.agents.verifier.run_prefetch_with_build_on_miss",
        new=AsyncMock(side_effect=PrefetchError(
            "sdist_only",
            "package=sentence-transformers version=2.2.2",
        )),
    ), patch(
        "src.agents.verifier._run_in_docker",
        new=AsyncMock(return_value=(0, "should not run")),
    ) as mock_docker:
        from src.agents.prefetch.manifest_finder import ManifestRef
        mock_find.return_value = ManifestRef(
            path=Path("requirements.txt"), kind="requirements",
        )

        v = HostedVerifier()
        result = await v.verify(
            repo_name="owner/repo",
            commit_sha="HEAD",
            diff="",
            language="Python",
            context={"repo_workdir": str(tmp_path)},
        )

        assert result.passed is False
        assert result.reason == "prefetch_failed_sdist_only"
        assert "sentence-transformers" in result.output
        # The docker call never ran.
        mock_docker.assert_not_called()


@pytest.mark.asyncio
async def test_build_on_miss_disabled_uses_run_prefetch(
    fake_repo, tmp_path, mock_prefetch_result, monkeypatch,
):
    """When BUILD_ON_MISS_ENABLED is false, the verifier calls
    run_prefetch instead of the with-build version."""
    monkeypatch.setattr(
        "src.agents.verifier.settings.BUILD_ON_MISS_ENABLED", False,
    )

    with patch(
        "src.agents.verifier.find_manifest",
    ) as mock_find, patch(
        "src.agents.verifier.run_prefetch",
        new=AsyncMock(return_value=mock_prefetch_result),
    ) as mock_prefetch, patch(
        "src.agents.verifier.run_prefetch_with_build_on_miss",
        new=AsyncMock(),
    ) as mock_with_build, patch(
        "src.agents.verifier._run_in_docker",
        new=AsyncMock(return_value=(0, "1 passed")),
    ):
        from src.agents.prefetch.manifest_finder import ManifestRef
        mock_find.return_value = ManifestRef(
            path=Path("requirements.txt"), kind="requirements",
        )

        v = HostedVerifier()
        await v.verify(
            repo_name="owner/repo",
            commit_sha="HEAD",
            diff="",
            language="Python",
            context={"repo_workdir": str(tmp_path)},
        )

        mock_prefetch.assert_awaited_once()
        mock_with_build.assert_not_called()


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
    assert "-r requirements.txt" in effective
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
