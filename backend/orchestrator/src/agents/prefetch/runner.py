"""
Run the prefetcher container and return its receipt.

The container is the same shape as the verifier's sandbox: an
ephemeral docker run, mounted data, controlled argv. Differences:

  - Network: yes (the prefetcher downloads wheels). The verifier
    runs with --network none.
  - Secrets: none. The container is started with no --env flags
    beyond MANIFEST_PATH, CACHE_DIR, and LOCK_PATH. No LLM keys,
    no DB URL, no GitHub token, no docker socket.
  - Image: stock python:3.11-slim. The entrypoint script is
    mounted read-only from a file the orchestrator stages into the
    cache directory.

Two filesystems, one function
─────────────────────────────

This module straddles two path namespaces:

  * The container's. What THIS process sees. `/app/...`,
    `/verifier-pip-cache/...`. Used by Path.read_text(),
    shutil.copy2(), mkdir() — any Python operation running in
    this process.

  * The host's. What the Docker DAEMON sees when it resolves a
    `-v` argument. On macOS: `/Users/.../aegis-pro/...`. On Linux
    in the compose layout: also something like `/home/.../`. The
    daemon resolves the string against the physical host
    filesystem, not against this container's.

The two are never interchangeable. `-v /verifier-pip-cache/...`
fails on macOS because the Mac has no `/verifier-pip-cache` — the
compose mount `./verifier-pip-cache:/verifier-pip-cache` maps the
Mac path `/Users/.../verifier-pip-cache` to the container path
`/verifier-pip-cache`, two different strings for the same bytes.

Therefore this function takes BOTH paths, explicitly. The caller
(the pipeline, or the test script) knows both:

    cache_container_path = Path("/verifier-pip-cache")
    cache_host_path      = Path(settings.VERIFIER_PIP_CACHE_HOST_DIR)

Staging bridges the two namespaces. The manifest and entrypoint
arrive as CONTAINER paths (this process can read them). They are
copied into the CONTAINER cache directory. The `-v` arguments then
reference the same files by their HOST paths, which the daemon can
resolve because the cache directory itself is a symmetric mount
in the compose file.

Why not translate /app/... to a host path with an
ORCHESTRATOR_HOST_DIR setting? Because it introduces a second
source of truth for the same fact. The compose mount
`./backend/orchestrator:/app` and a `${PWD}/backend/orchestrator`
env var are not mechanically coupled; they drift. Staging costs
one file copy per prefetch and eliminates the coupling entirely.
"""
from __future__ import annotations

import asyncio
import time
import shutil
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from src.agents.prefetch.receipt import (
    PrefetchReceipt,
    ReceiptError,
    parse_failure,
    parse_receipt,
)
from src.config import settings


PREFETCHER_IMAGE = "python:3.11-slim"

# Container-side mount points for the prefetcher container. These
# are NOT the same as the paths the orchestrator uses to read the
# files. They are where the daemon puts the mounted bytes inside
# the prefetcher, and where the entrypoint reads them.
ENTRYPOINT_IN_PREFETCHER = "/opt/prefetch_entrypoint.py"
MANIFEST_IN_PREFETCHER = "/manifest/requirements.txt"
CACHE_IN_PREFETCHER = "/pipcache"

# Filenames for the staged copies inside the cache directory. The
# leading underscore keeps them out of the way of wheel filenames
# (which never start with an underscore) so `iterdir()` in the
# entrypoint's enumeration step can't confuse them with artifacts.
STAGED_ENTRYPOINT_NAME = "_entrypoint.py"
STAGED_MANIFEST_NAME = "_manifest.txt"


class PrefetchError(Exception):
    """Infrastructure failure. Never a policy failure — those raise
    SanitizeError or PolicyError and are raised before we get here."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True)
class PrefetchResult:
    """
    Everything the caller (the verifier, in PR 2) needs.

    cache_container_path: container-side path of the populated
                          cache. The verifier reads from this
                          namespace when it mounts the cache
                          read-only into the verification container.

    cache_host_path:      host-side path of the same directory.
                          The verifier passes this to `docker run
                          -v` when it mounts the cache into the
                          verification container.

    lock_path:            container-side path of the lock file.

    receipt:              the parsed PrefetchReceipt.
    """
    cache_container_path: Path
    cache_host_path: Path
    lock_path: Path
    receipt: PrefetchReceipt


async def run_prefetch(
    *,
    manifest_container_path: Path,
    entrypoint_container_path: Path,
    cache_container_path: Path,
    cache_host_path: Path,
    timeout_seconds: int | None = None,
) -> PrefetchResult:
    """
    Spawn the prefetcher, wait for it, return the result.

    Arguments
    ---------
    manifest_container_path
        Where THIS process reads the manifest. e.g.
        Path("/app/requirements.txt").

    entrypoint_container_path
        Where THIS process reads the entrypoint script. e.g.
        Path("/app/scripts/prefetch_entrypoint.py").

    cache_container_path
        Where THIS process reads and writes the cache. e.g.
        Path("/verifier-pip-cache"). This is the container's view
        of the compose bind mount.

    cache_host_path
        What the Docker DAEMON sees the same cache directory as.
        e.g. Path("/Users/you/aegis-pro/verifier-pip-cache"). This
        is what gets passed to `docker run -v`. It is NEVER used
        for Python file operations in this function.
    """
    timeout = timeout_seconds or settings.VERIFIER_PREFETCH_TIMEOUT_SECONDS

    # ── Container-side file operations ─────────────────────────
    #
    # Everything below runs in THIS process. Paths are container
    # paths.

    cache_container_path.mkdir(parents=True, exist_ok=True)
    lock_path = cache_container_path / "requirements.lock"

    staged_entrypoint_container = (
        cache_container_path / STAGED_ENTRYPOINT_NAME
    )
    staged_manifest_container = (
        cache_container_path / STAGED_MANIFEST_NAME
    )

    shutil.copy2(entrypoint_container_path, staged_entrypoint_container)
    shutil.copy2(manifest_container_path, staged_manifest_container)

    # ── Host-side paths for docker run -v ──────────────────────
    #
    # Every -v argument uses cache_host_path. Because the staged
    # files live INSIDE the cache directory, their host-side paths
    # are cache_host_path / filename. Same directory the daemon is
    # already mounting.

    staged_entrypoint_host = (
        cache_host_path / STAGED_ENTRYPOINT_NAME
    )
    staged_manifest_host = (
        cache_host_path / STAGED_MANIFEST_NAME
    )

    argv = [
        "docker", "run", "--rm",
        "--network", settings.VERIFIER_PREFETCH_NETWORK,
        "--memory", settings.VERIFIER_PREFETCH_MEMORY_LIMIT,
        "--cpus", settings.VERIFIER_PREFETCH_CPU_LIMIT,
        "-v",
        f"{staged_entrypoint_host}:{ENTRYPOINT_IN_PREFETCHER}:ro",
        "-v",
        f"{staged_manifest_host}:{MANIFEST_IN_PREFETCHER}:ro",
        "-v",
        f"{cache_host_path}:{CACHE_IN_PREFETCHER}",
        "-e", f"MANIFEST_PATH={MANIFEST_IN_PREFETCHER}",
        "-e", f"CACHE_DIR={CACHE_IN_PREFETCHER}",
        "-e", f"LOCK_PATH={CACHE_IN_PREFETCHER}/requirements.lock",
        PREFETCHER_IMAGE,
        "python", ENTRYPOINT_IN_PREFETCHER,
    ]

    start = time.monotonic()
    logger.info(
        f"Prefetch: manifest={manifest_container_path.name} "
        f"cache_container={cache_container_path} "
        f"cache_host={cache_host_path}"
    )

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    try:
        stdout_bytes, _ = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        try:
            await proc.wait()
        except Exception:
            pass
        # Still clean up staged files before re-raising.
        _cleanup_staged(
            staged_entrypoint_container, staged_manifest_container,
        )
        raise PrefetchError("prefetch_timeout", f"exceeded {timeout}s")

    duration_ms = int((time.monotonic() - start) * 1000)
    stdout = stdout_bytes.decode("utf-8", errors="replace")

    _cleanup_staged(
        staged_entrypoint_container, staged_manifest_container,
    )

    if proc.returncode != 0:
        # The container may have emitted a structured diagnosis.
        # If so, use its named reason rather than the generic
        # "prefetch_crashed" with a raw stdout tail.
        failure = parse_failure(stdout)
        if failure is not None:
            raise PrefetchError(
                failure.reason,
                f"package={failure.package} "
                f"version={failure.version} "
                f"detail={failure.detail}",
            )
        tail = stdout[-4000:] if len(stdout) > 4000 else stdout
        raise PrefetchError(
            "prefetch_crashed",
            f"exit={proc.returncode} tail={tail!r}",
        )

    try:
        receipt = parse_receipt(stdout)
    except ReceiptError as e:
        tail = stdout[-2000:] if len(stdout) > 2000 else stdout
        raise PrefetchError(
            "prefetch_crashed",
            f"receipt parse failed: {e.reason}; tail={tail!r}",
        ) from e

    logger.info(
        f"Prefetch: {len(receipt.packages)} packages, "
        f"fetched_now={receipt.fetched_now}, "
        f"container_duration={duration_ms}ms"
    )

    return PrefetchResult(
        cache_container_path=cache_container_path,
        cache_host_path=cache_host_path,
        lock_path=lock_path,
        receipt=receipt,
    )


def _cleanup_staged(*paths: Path) -> None:
    """Remove staged files. Best-effort — a leftover _entrypoint.py
    in the cache directory isn't fatal, just untidy."""
    for p in paths:
        try:
            p.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Prefetch: could not remove {p}: {e}")
