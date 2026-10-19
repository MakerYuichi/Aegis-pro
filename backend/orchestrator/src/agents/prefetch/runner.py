from __future__ import annotations
from typing import Optional

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
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.agents.prefetch.receipt import PrefetchFailure
    from src.agents.mirror.types import SdistRef


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

async def run_prefetch_with_build_on_miss(
    *,
    manifest_container_path: Path,
    entrypoint_container_path: Path,
    cache_container_path: Path,
    cache_host_path: Path,
    mirror_container_path: Path,
    mirror_host_path: Path,
    build_entrypoint_container_path: Path,
    timeout_seconds: int | None = None,
) -> PrefetchResult:
    """
    Run the prefetcher. On `sdist_only`, build the missing wheel
    and retry once with --find-links pointing at the mirror.

    The prefetcher's container does the actual pip download; it
    cannot call the build pipeline itself. So this function
    orchestrates the two:

        1. Run run_prefetch. It fails with sdist_only.
        2. Parse the failure. Fetch the sdist, build a wheel,
           publish to the mirror.
        3. Run run_prefetch again with EXTRA_FIND_LINKS set to the
           published directory.

    Bounded to one retry. A second sdist_only failure is a bug in
    the build pipeline or in pip's ability to see the mirror
    directory, and it's reported as-is rather than looping.
    """
    from src.agents.mirror.fetch_sdist import SdistFetchError, fetch_sdist
    from src.agents.mirror.integrate import (
        IntegrateError,
        build_from_sdist_failure,
    )
    from src.agents.mirror.resolver import BuildResolver
    from src.agents.mirror.types import SdistRef
    import urllib.request
    import json

    try:
        return await run_prefetch(
            manifest_container_path=manifest_container_path,
            entrypoint_container_path=entrypoint_container_path,
            cache_container_path=cache_container_path,
            cache_host_path=cache_host_path,
            timeout_seconds=timeout_seconds,
        )
    except PrefetchError as e:
        if e.reason != "sdist_only":
            raise
        # PEP 3110: `e` is deleted at the end of the except block.
        # Copy what we need before the block exits.
        first_failure_detail = e.detail

    logger.info(
        f"Prefetch: sdist_only on {first_failure_detail}; "
        f"building and retrying"
    )

    failure = parse_failure_from_detail(first_failure_detail)
    if failure is None:
        raise PrefetchError(
            "sdist_only_unrecoverable",
            f"could not parse failure detail: {first_failure_detail}",
        )

    sdist_ref = await _fetch_sdist_ref(failure.package, failure.version)
    if sdist_ref is None:
        raise PrefetchError(
            "sdist_ref_unresolved",
            f"{failure.package} {failure.version}: "
            f"no sdist URL found on PyPI",
        )

    resolver = BuildResolver()
    python_tag = _python_tag_from_platform()
    try:
        wheel_dir_host = await build_from_sdist_failure(
            failure=failure,
            sdist_ref=sdist_ref,
            mirror_host_dir=mirror_host_path,
            mirror_container_dir=mirror_container_path,
            entrypoint_container_path=build_entrypoint_container_path,
            resolver=resolver,
            python_tag=python_tag,
        )
    except IntegrateError as ex:
        raise PrefetchError(
            f"build_on_miss_{ex.reason}",
            ex.detail,
        ) from ex

    # Retry the prefetcher with the mirror directory as a find-links.
    # The wheel directory's host path is the same as its container
    # path because the mirror mount is symmetric in compose.
    wheel_dir_container = (
        mirror_container_path
        / wheel_dir_host.relative_to(mirror_host_path)
    )

    return await _retry_with_find_links(
        manifest_container_path=manifest_container_path,
        entrypoint_container_path=entrypoint_container_path,
        cache_container_path=cache_container_path,
        cache_host_path=cache_host_path,
        find_links_container=wheel_dir_container,
        find_links_host=wheel_dir_host,
        timeout_seconds=timeout_seconds,
    )


async def _retry_with_find_links(
    *,
    manifest_container_path: Path,
    entrypoint_container_path: Path,
    cache_container_path: Path,
    cache_host_path: Path,
    find_links_container: Path,
    find_links_host: Path,
    timeout_seconds: int | None,
) -> PrefetchResult:
    """
    Run the prefetcher with EXTRA_FIND_LINKS set.

    The find-links directory has to be visible to the container
    running pip download. In compose the mirror is bind-mounted at
    MIRROR_CONTAINER_DIR inside the orchestrator, and at
    MIRROR_HOST_DIR on the host. But the prefetcher is a SIBLING
    container — it doesn't share the orchestrator's mount. So we
    mount the find-links directory explicitly, at a known path.
    """
    from src.agents.prefetch.receipt import parse_receipt

    FIND_LINKS_IN_PREFETCHER = "/findlinks"

    timeout = timeout_seconds or settings.VERIFIER_PREFETCH_TIMEOUT_SECONDS

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
        "-v",
        f"{find_links_host}:{FIND_LINKS_IN_PREFETCHER}:ro",
        "-e", f"MANIFEST_PATH={MANIFEST_IN_PREFETCHER}",
        "-e", f"CACHE_DIR={CACHE_IN_PREFETCHER}",
        "-e", f"LOCK_PATH={CACHE_IN_PREFETCHER}/requirements.lock",
        "-e", f"EXTRA_FIND_LINKS={FIND_LINKS_IN_PREFETCHER}",
        PREFETCHER_IMAGE,
        "python", ENTRYPOINT_IN_PREFETCHER,
    ]

    start = time.monotonic()
    logger.info(f"Prefetch retry: find_links={find_links_host}")

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
        failure = parse_failure(stdout)
        if failure is not None:
            raise PrefetchError(
                f"retry_{failure.reason}",
                f"package={failure.package} "
                f"version={failure.version} "
                f"detail={failure.detail}",
            )
        tail = stdout[-4000:] if len(stdout) > 4000 else stdout
        raise PrefetchError(
            "prefetch_retry_crashed",
            f"exit={proc.returncode} tail={tail!r}",
        )

    try:
        receipt = parse_receipt(stdout)
    except ReceiptError as rx:
        tail = stdout[-2000:] if len(stdout) > 2000 else stdout
        raise PrefetchError(
            "prefetch_retry_crashed",
            f"receipt parse failed: {rx.reason}; tail={tail!r}",
        ) from rx

    logger.info(
        f"Prefetch retry succeeded: {len(receipt.packages)} "
        f"packages, {duration_ms}ms"
    )
    return PrefetchResult(
        cache_container_path=cache_container_path,
        cache_host_path=cache_host_path,
        lock_path=lock_path,
        receipt=receipt,
    )


def parse_failure_from_detail(detail: str) -> Optional["PrefetchFailure"]:
    """
    Reconstruct a PrefetchFailure from the detail string that
    PrefetchError carries. The detail is in the form
    'package=X version=Y detail=Z'. That's what
    `run_prefetch` builds from `parse_failure`.
    """
    import re
    from src.agents.prefetch.receipt import PrefetchFailure

    m = re.search(
        r"package=(\S+) version=(\S+) detail=(.*)",
        detail, re.DOTALL,
    )
    if m is None:
        return None
    return PrefetchFailure(
        reason="sdist_only",
        detail=m.group(3),
        package=m.group(1),
        version=m.group(2),
        available_wheels=[],
        index_url="",
    )


async def _fetch_sdist_ref(
    name: str, version: str,
) -> "SdistRef | None":
    """
    Look up the sdist for (name, version) on PyPI and return an
    SdistRef. Returns None if no sdist is published.
    """
    from src.agents.mirror.types import SdistRef
    import urllib.request
    import json

    url = f"https://pypi.org/pypi/{name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as ex:
        logger.warning(
            f"Prefetch: could not look up sdist for {name} "
            f"{version}: {ex}"
        )
        return None

    for f in payload.get("urls") or []:
        if f.get("packagetype") == "sdist":
            return SdistRef(
                url=f["url"],
                filename=f["filename"],
                sha256="sha256:" + f["digests"]["sha256"],
                upload_time=f["upload_time_iso_8601"],
                name=name,
                version=version,
            )
    return None


def _python_tag_from_platform() -> str:
    """Compute the pip-style python tag for the current interpreter."""
    import platform
    v = platform.python_version().split(".")
    return f"cp{v[0]}{v[1]}"
