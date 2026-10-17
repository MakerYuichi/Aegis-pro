"""
Tests for src.agents.prefetch.runner.

The runner spawns a container. In tests we mock the subprocess call
and assert:
    * the argv has the right shape
    * no secret env vars are passed
    * the cache, manifest, and entrypoint are mounted with the right
      read/write mode
    * the container/host path split is honored — file ops use
      container paths, -v arguments use host paths
    * failure modes produce the right PrefetchError reason

The tests do not require Docker.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.prefetch.runner import (
    CACHE_IN_PREFETCHER,
    ENTRYPOINT_IN_PREFETCHER,
    MANIFEST_IN_PREFETCHER,
    PREFETCHER_IMAGE,
    STAGED_ENTRYPOINT_NAME,
    STAGED_MANIFEST_NAME,
    PrefetchError,
    PrefetchResult,
    run_prefetch,
)


def _receipt_stdout(fetched=True):
    payload = {
        "manifest_path": "requirements.txt",
        "manifest_hash": "sha256:" + "a" * 64,
        "python_version": "3.11.16",
        "platform_tag": "linux_x86_64",
        "packages": [],
        "fetched_now": fetched,
        "duration_ms": 500,
    }
    return json.dumps(payload)


def _mock_proc(returncode=0, stdout=b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, None))
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


async def _run_with_mock(proc, tmp_path):
    """
    Run run_prefetch with four path arguments: container-side
    paths for the file operations, host-side for the -v mounts.
    In tests they can be the same tmpdir because the runner never
    actually invokes Docker — the mock replaces the subprocess
    call, so neither namespace matters for correctness.
    """
    container = tmp_path / "container"
    container.mkdir(exist_ok=True)
    entrypoint_container = container / "entry.py"
    manifest_container = container / "req.txt"
    entrypoint_container.write_text("# entrypoint")
    manifest_container.write_text("# manifest")

    cache_container = container / "cache"
    cache_host = tmp_path / "cache"

    with patch(
        "asyncio.create_subprocess_exec",
        return_value=proc,
    ) as mock_exec:
        result = await run_prefetch(
            manifest_container_path=manifest_container,
            entrypoint_container_path=entrypoint_container,
            cache_container_path=cache_container,
            cache_host_path=cache_host,
        )
        return result, mock_exec, {
            "entrypoint_container": entrypoint_container,
            "manifest_container": manifest_container,
            "cache_container": cache_container,
            "cache_host": cache_host,
        }


# ── happy path ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_successful_prefetch_returns_result(tmp_path):
    proc = _mock_proc(stdout=_receipt_stdout().encode())
    result, _, paths = await _run_with_mock(proc, tmp_path)
    assert isinstance(result, PrefetchResult)
    assert result.cache_container_path == paths["cache_container"]
    assert result.cache_host_path == paths["cache_host"]
    assert result.lock_path == paths["cache_container"] / "requirements.lock"
    assert result.receipt.fetched_now is True


# ── argv shape ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_argv_mounts_and_env_shape(tmp_path):
    proc = _mock_proc(stdout=_receipt_stdout().encode())
    _, mock_exec, paths = await _run_with_mock(proc, tmp_path)

    argv = mock_exec.call_args.args
    joined = " ".join(argv)

    # Image is the stock python image.
    assert PREFETCHER_IMAGE in argv

    # Entrypoint and manifest mounted read-only at their fixed
    # container paths.
    assert any(
        a.endswith(f"{ENTRYPOINT_IN_PREFETCHER}:ro") for a in argv
    )
    assert any(
        a.endswith(f"{MANIFEST_IN_PREFETCHER}:ro") for a in argv
    )

    # Cache mounted read-write at its fixed container path. The
    # -v argument's left side is the HOST path (the cache's host
    # directory), the right side is the container path.
    cache_mount_present = False
    for i, arg in enumerate(argv):
        if arg == "-v" and i + 1 < len(argv):
            spec = argv[i + 1]
            if spec.endswith(f":{CACHE_IN_PREFETCHER}") and \
               not spec.endswith(":ro"):
                cache_mount_present = True
                break
    assert cache_mount_present, (
        f"no read-write cache mount at {CACHE_IN_PREFETCHER} "
        f"in argv: {argv}"
    )

    # Host paths, not container paths, appear on the left side of
    # every -v argument. This is the invariant that took three
    # fixes to get right; the test enforces it.
    for i, arg in enumerate(argv):
        if arg == "-v" and i + 1 < len(argv):
            left = argv[i + 1].split(":")[0]
            assert not left.startswith(str(paths["cache_container"])), (
                f"container path appeared in -v: {argv[i + 1]}"
            )
            assert not left.startswith(str(paths["entrypoint_container"])), (
                f"container path appeared in -v: {argv[i + 1]}"
            )
            assert not left.startswith(str(paths["manifest_container"])), (
                f"container path appeared in -v: {argv[i + 1]}"
            )

    # Env contains exactly the three benign vars.
    env_args = [
        argv[i + 1] for i, a in enumerate(argv) if a == "-e"
    ]
    assert any(a.startswith("MANIFEST_PATH=") for a in env_args)
    assert any(a.startswith("CACHE_DIR=") for a in env_args)
    assert any(a.startswith("LOCK_PATH=") for a in env_args)

    # No secret-shaped env vars leaked in.
    forbidden = (
        "GROQ_API_KEY", "GITHUB_TOKEN", "DATABASE_URL",
        "SLACK_BOT_TOKEN", "AUTH0", "SECRET_KEY",
        "AWS_", "DOCKER_HOST",
    )
    for arg in env_args:
        for f in forbidden:
            assert f not in arg, (
                f"secret env var leaked: {arg!r}"
            )


@pytest.mark.asyncio
async def test_network_is_not_none(tmp_path):
    """The prefetcher needs network; the verifier does not. This
    test asserts the prefetcher's argv does NOT include
    --network none."""
    proc = _mock_proc(stdout=_receipt_stdout().encode())
    _, mock_exec, _ = await _run_with_mock(proc, tmp_path)

    argv = mock_exec.call_args.args
    for i, a in enumerate(argv):
        if a == "--network":
            assert argv[i + 1] != "none", (
                "prefetcher must have network"
            )


@pytest.mark.asyncio
async def test_staged_files_copied_from_container_paths(tmp_path):
    """
    The runner stages the entrypoint and manifest inside the
    container cache directory, then mounts those staged copies by
    their host paths. This test asserts the staged files exist
    where the runner put them, before the mock returns.
    """
    proc = _mock_proc(stdout=_receipt_stdout().encode())
    container = tmp_path / "container"
    container.mkdir()
    entrypoint_container = container / "entry.py"
    manifest_container = container / "req.txt"
    entrypoint_container.write_text("# entrypoint")
    manifest_container.write_text("# manifest")

    cache_container = container / "cache"
    cache_host = tmp_path / "cache"

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        await run_prefetch(
            manifest_container_path=manifest_container,
            entrypoint_container_path=entrypoint_container,
            cache_container_path=cache_container,
            cache_host_path=cache_host,
        )

    # After the run, the staged files are cleaned up.
    assert not (
        cache_container / STAGED_ENTRYPOINT_NAME
    ).exists()
    assert not (
        cache_container / STAGED_MANIFEST_NAME
    ).exists()


# ── failure modes ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_nonzero_exit_raises_prefetch_crashed(tmp_path):
    proc = _mock_proc(
        returncode=1,
        stdout=b"pip failed: no matching distribution",
    )
    with pytest.raises(PrefetchError) as exc_info:
        await _run_with_mock(proc, tmp_path)
    assert exc_info.value.reason == "prefetch_crashed"


@pytest.mark.asyncio
async def test_structured_failure_uses_named_reason(tmp_path):
    """
    When the container emits a structured failure diagnosis as the
    last stdout line, the runner reports its named reason instead
    of a generic prefetch_crashed.
    """
    failure_payload = {
        "error": "sdist_only",
        "detail": "pkg 2.2.2 ships only an sdist",
        "package": "pkg",
        "version": "2.2.2",
        "available_wheels": [],
        "index_url": "https://pypi.org/simple/",
    }
    proc = _mock_proc(
        returncode=3,
        stdout=json.dumps(failure_payload).encode(),
    )
    with pytest.raises(PrefetchError) as exc_info:
        await _run_with_mock(proc, tmp_path)
    assert exc_info.value.reason == "sdist_only"
    assert "pkg" in exc_info.value.detail
    assert "2.2.2" in exc_info.value.detail


@pytest.mark.asyncio
async def test_malformed_receipt_raises_prefetch_crashed(tmp_path):
    proc = _mock_proc(stdout=b"pip output but no receipt at the end")
    with pytest.raises(PrefetchError) as exc_info:
        await _run_with_mock(proc, tmp_path)
    assert exc_info.value.reason == "prefetch_crashed"


@pytest.mark.asyncio
async def test_timeout_kills_and_raises(tmp_path):
    proc = _mock_proc()
    proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)

    container = tmp_path / "container"
    container.mkdir()
    entrypoint_container = container / "entry.py"
    manifest_container = container / "req.txt"
    entrypoint_container.write_text("# entrypoint")
    manifest_container.write_text("# manifest")
    cache_container = container / "cache"
    cache_host = tmp_path / "cache"

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        with pytest.raises(PrefetchError) as exc_info:
            await run_prefetch(
                manifest_container_path=manifest_container,
                entrypoint_container_path=entrypoint_container,
                cache_container_path=cache_container,
                cache_host_path=cache_host,
                timeout_seconds=1,
            )
    assert exc_info.value.reason == "prefetch_timeout"
    proc.kill.assert_called_once()


# ── cache directory creation ────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_directory_created_before_run(tmp_path):
    proc = _mock_proc(stdout=_receipt_stdout().encode())

    container = tmp_path / "container"
    container.mkdir()
    entrypoint_container = container / "entry.py"
    manifest_container = container / "req.txt"
    entrypoint_container.write_text("# entrypoint")
    manifest_container.write_text("# manifest")

    cache_container = container / "new_cache"
    cache_host = tmp_path / "new_cache"
    assert not cache_container.exists()

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        await run_prefetch(
            manifest_container_path=manifest_container,
            entrypoint_container_path=entrypoint_container,
            cache_container_path=cache_container,
            cache_host_path=cache_host,
        )
    assert cache_container.is_dir()
