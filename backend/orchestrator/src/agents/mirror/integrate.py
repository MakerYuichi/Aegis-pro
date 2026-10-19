"""
Integration: build-on-miss for sdist-only packages.

Called from the prefetch runner after a `sdist_only` failure.
Reads the sdist, resolves build requirements, builds a wheel in
a sandboxed container, publishes it to the mirror, and returns.

The result is a mirror directory path the prefetcher's pip download
can be retried against with --find-links.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from loguru import logger
from src.config import settings

from src.agents.mirror.build import BuildError, build_sdist
from src.agents.mirror.fetch_sdist import SdistFetchError, fetch_sdist
from src.agents.mirror.preflight import (
    PreflightError, check_builder_verifier_match,
)
from src.agents.mirror.resolver import BuildResolver, ResolverError
from src.agents.mirror.sdist_reader import (
    SdistReaderError, read_build_system_requires,
)
from src.agents.mirror.smoke import SmokeError, smoke_test
from src.agents.mirror.types import SdistRef
from src.agents.mirror.writer import publish_built_wheel, PublishError
from src.agents.prefetch.receipt import PrefetchFailure


PIP_DEFAULT_BUILD_REQUIRES = "setuptools>=40.8.0"


class IntegrateError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


async def build_from_sdist_failure(
    *,
    failure: PrefetchFailure,
    sdist_ref: SdistRef,
    mirror_host_dir: Path,
    mirror_container_dir: Path,
    entrypoint_container_path: Path,
    resolver: BuildResolver,
    python_tag: str,
) -> Path:
    """
    Execute the full build-on-miss flow.

    Returns the host-side path of the wheel directory that the
    prefetcher can retry pip download against with --find-links.

    Raises IntegrateError with a specific reason on any failure.
    """
    try:
        await check_builder_verifier_match()
    except PreflightError as e:
        raise IntegrateError(e.reason, e.detail) from e

    # 1. Fetch the sdist.
    try:
        sdist_bytes = fetch_sdist(sdist_ref)
    except SdistFetchError as e:
        raise IntegrateError(e.reason, e.detail) from e

    # 2. Read the build-system.requires.
    try:
        requires = read_build_system_requires(sdist_bytes)
    except SdistReaderError as e:
        raise IntegrateError(e.reason, e.detail) from e

    # 3. Fall back to pip's default for legacy sdists.
    from src.agents.mirror.types import BuildRequirement
    if not requires:
        requires = [BuildRequirement(
            name="setuptools",
            specifier=">=40.8.0",
            source="default",
            raw_line=PIP_DEFAULT_BUILD_REQUIRES,
        )]

    # 4. Resolve each requirement.
    outcome = resolver.resolve_all(
        requires,
        as_of=sdist_ref.upload_time,
        python_tag=python_tag,
    )
    if not outcome.success:
        raise IntegrateError(
            f"build_req_{outcome.failed_reason}",
            f"{outcome.failed_name}: {outcome.failed_detail}",
        )

    # 5. Stage the build entrypoint into the mirror directory so
    #    its host-side path is the same as its container-side path.
    #    The mirror mount is symmetric in compose, so once the
    #    entrypoint is inside it, the Docker daemon can resolve it.
    #
    #    This requires MIRROR_HOST_DIR to be the actual host-side
    #    path. If it's the config default (/var/lib/aegis/mirror),
    #    the daemon will mount an empty file. The compose file
    #    must set MIRROR_HOST_DIR=${PWD}/mirror in the orchestrator
    #    environment.
    # Only the container-side path can be checked from inside
    # this process. The host-side path resolves on the Docker
    # daemon, not here — asserting on it would fail for any
    # correctly-configured deployment, since the orchestrator
    # container has no /Users/... (or /home/...) filesystem.
    # If the host path is wrong, the build container's mount
    # will fail with the entrypoint staging check or with an
    # empty-file error, both of which are named and actionable.
    if not mirror_container_dir.is_dir():
        raise IntegrateError(
            "mirror_dir_missing",
            f"{mirror_container_dir} does not exist. The mirror "
            f"bind mount is missing from docker-compose.yml.",
        )

    staged_entrypoint_container = (
        mirror_container_dir / ".build_entrypoint.py"
    )
    staged_entrypoint_host = (
        mirror_host_dir / ".build_entrypoint.py"
    )
    shutil.copy2(entrypoint_container_path, staged_entrypoint_container)

    if not staged_entrypoint_container.is_file() or \
       staged_entrypoint_container.stat().st_size == 0:
        raise IntegrateError(
            "build_entrypoint_staged_empty",
            f"{staged_entrypoint_container} is empty after copy "
            f"from {entrypoint_container_path}",
        )

    # 6. Build in a temp directory that resolves on BOTH sides.
    #    The Docker daemon resolves -v paths against the host, so
    #    we create the temp dir under a host-mounted directory
    #    (VERIFIER_CONTAINER_WORKDIR, which maps to
    #    VERIFIER_HOST_WORKDIR) and derive the host path by
    #    replacing the container prefix with the host prefix.
    workdir_parent_container = Path(settings.VERIFIER_CONTAINER_WORKDIR)
    workdir_parent_host = Path(settings.VERIFIER_HOST_WORKDIR)
    workdir_parent_container.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="aegis-build-", dir=workdir_parent_container,
    ) as tmp_container_str:
        tmp_container_path = Path(tmp_container_str)
        relative = tmp_container_path.relative_to(workdir_parent_container)
        tmp_host_path = workdir_parent_host / relative

        wheelhouse_container = tmp_container_path / "wheelhouse"
        wheelhouse_host = tmp_host_path / "wheelhouse"
        wheelhouse_container.mkdir()
        await _ensure_wheelhouse(wheelhouse_container, outcome.resolved)

        workdir_container = tmp_container_path / "build"
        workdir_host = tmp_host_path / "build"
        workdir_container.mkdir()
        (workdir_container / "out").mkdir()

        sdist_file_container = tmp_container_path / "source.tar.gz"
        sdist_file_container.write_bytes(sdist_bytes)

        try:
            built = await build_sdist(
                sdist_path=tmp_host_path / "source.tar.gz",
                wheelhouse_dir=wheelhouse_host,
                entrypoint_host_path=staged_entrypoint_host,
                workdir_host_path=workdir_host,
                workdir_container_path=workdir_container,
            )
        except BuildError as e:
            raise IntegrateError(e.reason, e.detail) from e

        # Smoke test the wheel before it reaches the mirror.
        # Refuses a wheel that doesn't match the pin, whose tags
        # aren't supported by the verifier, whose RECORD is
        # inconsistent, or whose modules can't be found by
        # find_spec in a container running the verifier image.
        #
        # The smoke test runs on newly built wheels only —
        # publish_built_wheel's idempotent check short-circuits
        # before this point on a cache hit, so a wheel that's
        # already in the mirror (and was validated when it was
        # first published) isn't re-validated on every prefetch.
        try:
            await smoke_test(
                wheel_container_path=built.wheel_path,
                wheel_host_path=workdir_host / "out" / built.wheel_path.name,
                expected_name=sdist_ref.name,
                expected_version=sdist_ref.version,
            )
        except SmokeError as e:
            raise IntegrateError(
                f"smoke_failed_{e.reason}", e.detail,
            ) from e

        try:
            wheel_dir_host = publish_built_wheel(
                built=built,
                sdist_ref=sdist_ref,
                requires=outcome.resolved,
                mirror_container_dir=mirror_container_dir,
                mirror_host_dir=mirror_host_dir,
            )
        except PublishError as e:
            raise IntegrateError(e.reason, e.detail) from e

    logger.info(
        f"build_from_sdist_failure: {sdist_ref.name} "
        f"{sdist_ref.version} → {wheel_dir_host}"
    )
    return wheel_dir_host


async def _ensure_wheelhouse(
    wheelhouse: Path, resolved: list,
) -> None:
    """
    Download wheels for every resolved build requirement into the
    wheelhouse.

    Runs pip download --no-deps --only-binary=:all: against
    temporary group files with exact pins. The download happens in
    this process (the orchestrator), which is the trusted phase
    with network. The build container later reads from the
    wheelhouse with --network none.

    Groups by source_index so build requirements that route to a
    non-PyPI index (torch-family) go to the right host. Bounded per
    invocation by BUILD_RESOLVER_TIMEOUT_SECONDS * 10.

    Confirms every resolved requirement's wheel actually landed
    before returning. A missing wheel is a failure, not a warning —
    the build would fail on it anyway, and failing here gives a
    cleaner reason.
    """
    import subprocess
    import sys
    from src.agents.prefetch.sanitize import normalize_name
    from src.config import settings

    if not resolved:
        return

    wheelhouse.mkdir(parents=True, exist_ok=True)

    by_index: dict[str, list[str]] = {}
    for r in resolved:
        by_index.setdefault(r.source_index, []).append(
            f"{r.name}=={r.version}"
        )

    for index_url, specs in by_index.items():
        group_file = wheelhouse / "_group.txt"
        group_file.write_text(
            "\n".join(specs) + "\n", encoding="utf-8",
        )
        argv = [
            sys.executable, "-m", "pip", "download",
            "--no-deps",
            "--only-binary=:all:",
            "--index-url", index_url,
            "--dest", str(wheelhouse),
            "--no-cache-dir",
            "-r", str(group_file),
        ]
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True,
                timeout=settings.BUILD_RESOLVER_TIMEOUT_SECONDS * 10,
            )
        finally:
            group_file.unlink(missing_ok=True)

        if proc.returncode != 0:
            raise IntegrateError(
                "wheelhouse_fetch_failed",
                f"{index_url}: "
                f"{(proc.stderr or proc.stdout or '')[:500]}",
            )

    # Confirm every requirement landed.
    present: set[str] = set()
    for whl in wheelhouse.glob("*.whl"):
        # Wheel filenames are `{name}-{version}-...whl`. The name
        # portion may contain hyphens converted to underscores by
        # the packaging tools; normalize_name handles both.
        name = whl.name.split("-")[0]
        present.add(normalize_name(name))
    missing = [r.name for r in resolved if r.name not in present]
    if missing:
        raise IntegrateError(
            "wheelhouse_incomplete",
            f"missing wheels: {missing}",
        )
