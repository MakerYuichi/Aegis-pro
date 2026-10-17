"""
Tests for src.agents.prefetch.runner.

The runner spawns a container. In tests we mock the subprocess call
and assert:
    * the argv has the right shape
    * no secret env vars are passed
    * the cache, manifest, and entrypoint are mounted with the right
      read/write mode
    * failure modes produce the right PrefetchError reason

The tests do not require Docker.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.prefetch.receipt import ReceiptError
from src.agents.prefetch.runner import (
    CACHE_CONTAINER_PATH,
    ENTRYPOINT_CONTAINER_PATH,
    MANIFEST_CONTAINER_PATH,
    PREFETCHER_IMAGE,
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
    with patch(
        "asyncio.create_subprocess_exec",
        return_value=proc,
    ) as mock_exec:
        result = await run_prefetch(
            manifest_host_path=tmp_path / "req.txt",
            cache_host_path=tmp_path / "cache",
            entrypoint_host_path=tmp_path / "entry.py",
        )
        return result, mock_exec


# ── happy path ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_successful_prefetch_returns_result(tmp_path):
    proc = _mock_proc(stdout=_receipt_stdout().encode())
    result, _ = await _run_with_mock(proc, tmp_path)
    assert isinstance(result, PrefetchResult)
    assert result.cache_dir == tmp_path / "cache"
    assert result.lock_path == tmp_path / "cache" / "requirements.lock"
    assert result.receipt.fetched_now is True


# ── argv shape ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_argv_mounts_and_env_shape(tmp_path):
    proc = _mock_proc(stdout=_receipt_stdout().encode())
    _, mock_exec = await _run_with_mock(proc, tmp_path)

    argv = mock_exec.call_args.args
    joined = " ".join(argv)

    # image is the stock python image
    assert PREFETCHER_IMAGE in argv

    # entrypoint and manifest mounted read-only
    assert any(
        a.endswith(f"{ENTRYPOINT_CONTAINER_PATH}:ro") for a in argv
    )
    assert any(
        a.endswith(f"{MANIFEST_CONTAINER_PATH}:ro") for a in argv
    )

    # cache mounted read-write (no :ro suffix)
    assert any(
        CACHE_CONTAINER_PATH in a and not a.endswith(":ro")
        for a in argv
    )

    # env contains exactly the three benign vars
    env_args = [
        argv[i + 1] for i, a in enumerate(argv) if a == "-e"
    ]
    assert any(a.startswith("MANIFEST_PATH=") for a in env_args)
    assert any(a.startswith("CACHE_DIR=") for a in env_args)
    assert any(a.startswith("LOCK_PATH=") for a in env_args)

    # no secret-shaped env vars leaked in
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
    _, mock_exec = await _run_with_mock(proc, tmp_path)

    argv = mock_exec.call_args.args
    for i, a in enumerate(argv):
        if a == "--network":
            assert argv[i + 1] != "none", (
                "prefetcher must have network"
            )


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
async def test_malformed_receipt_raises_prefetch_crashed(tmp_path):
    proc = _mock_proc(stdout=b"pip output but no receipt at the end")
    with pytest.raises(PrefetchError) as exc_info:
        await _run_with_mock(proc, tmp_path)
    assert exc_info.value.reason == "prefetch_crashed"


@pytest.mark.asyncio
async def test_timeout_kills_and_raises(tmp_path):
    proc = _mock_proc()
    proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
    with patch(
        "asyncio.create_subprocess_exec", return_value=proc,
    ):
        with pytest.raises(PrefetchError) as exc_info:
            await run_prefetch(
                manifest_host_path=tmp_path / "req.txt",
                cache_host_path=tmp_path / "cache",
                entrypoint_host_path=tmp_path / "entry.py",
                timeout_seconds=1,
            )
    assert exc_info.value.reason == "prefetch_timeout"
    proc.kill.assert_called_once()


# ── cache directory creation ────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_directory_created_before_run(tmp_path):
    cache_dir = tmp_path / "new_cache"
    assert not cache_dir.exists()
    proc = _mock_proc(stdout=_receipt_stdout().encode())
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        await run_prefetch(
            manifest_host_path=tmp_path / "req.txt",
            cache_host_path=cache_dir,
            entrypoint_host_path=tmp_path / "entry.py",
        )
    assert cache_dir.is_dir()
