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

from src.agents.mirror.build import BuildError, build_sdist
from src.agents.mirror.fetch_sdist import SdistFetchError, fetch_sdist
from src.agents.mirror.preflight import (
    PreflightError, check_builder_verifier_match,
)
from src.agents.mirror.resolver import BuildResolver, ResolverError
from src.agents.mirror.sdist_reader import (
    SdistReaderError, read_build_system_requires,
)
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
    entrypoint_host_path: Path,
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

    # 5. Prefetch the build requirements into a temporary wheelhouse.
    #    This reuses the existing prefetcher's container. The
    #    wheelhouse is temporary — it exists only for this build.
    with tempfile.TemporaryDirectory(prefix="aegis-build-") as tmp:
        tmp_path = Path(tmp)
        wheelhouse = tmp_path / "wheelhouse"
        wheelhouse.mkdir()
        # (Fetching build-requirement wheels is delegated to the
        # caller in the prefetcher's container; for now we assert
        # they're present. This is a stub that the prefetcher's
        # integration fills in.)
        _ensure_wheelhouse(wheelhouse, outcome.resolved)

        # 6. Build the sdist in a fresh workdir.
        workdir = tmp_path / "build"
        workdir.mkdir()

        sdist_file = tmp_path / "source.tar.gz"
        sdist_file.write_bytes(sdist_bytes)

        try:
            built = await build_sdist(
                sdist_path=sdist_file,
                wheelhouse_dir=wheelhouse,
                entrypoint_host_path=entrypoint_host_path,
                workdir_host_path=workdir,
            )
        except BuildError as e:
            raise IntegrateError(e.reason, e.detail) from e

        # 7. Publish to the mirror under the sdist's sha256.
        try:
            wheel_dir_host = publish_built_wheel(
                built=built,
                sdist_ref=sdist_ref,
                requires=outcome.resolved,
                mirror_host_dir=mirror_host_dir,
            )
        except PublishError as e:
            raise IntegrateError(e.reason, e.detail) from e

    logger.info(
        f"build_from_sdist_failure: {sdist_ref.name} "
        f"{sdist_ref.version} → {wheel_dir_host}"
    )
    return wheel_dir_host


def _ensure_wheelhouse(wheelhouse: Path, resolved: list) -> None:
    """
    Ensure the wheelhouse contains a wheel for every resolved
    build requirement.

    In C1b this is a stub: it asserts the wheels exist and raises
    otherwise. The prefetcher's retry integration in C1c will run
    the actual pip download of build requirements into the
    wheelhouse before invoking the build.
    """
    if not resolved:
        return
    present = {p.name for p in wheelhouse.glob("*.whl")}
    missing = [r.name for r in resolved if r.name not in present]
    if missing:
        raise IntegrateError(
            "wheelhouse_incomplete",
            f"missing wheels: {missing}",
        )
