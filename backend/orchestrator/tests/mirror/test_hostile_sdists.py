"""
Tests for the hostile sdist fixtures.

Each test asserts:
  - The pipeline refuses the attack.
  - The refusal names a specific reason.

Not every test runs the full pipeline. Some tests exercise the
orchestrator-side defenses (safe_tar, validate_member_names) in
isolation, because those are what refuse the tarball before the
build container even starts. Running a full pipeline for a
tarball that's refused at the orchestrator level would just
confirm the refusal, at higher cost.

Tests are marked `requires_docker` when they spawn a build
container. Tests that only exercise orchestrator-side code
aren't marked and run without Docker.

Two-namespace staging
─────────────────────

build_sdist's -v arguments resolve on the Docker daemon against
the HOST filesystem. Anything under the orchestrator's own
/tmp is invisible to the daemon. Every input that becomes a -v
argument must be staged under VERIFIER_CONTAINER_WORKDIR (which
is bind-mounted from VERIFIER_HOST_WORKDIR) and referenced by
its host-side equivalent.

The `_stage` helper below returns (container_path, host_path)
for a given relative name under a unique per-test subdirectory.
Every Docker-required test uses it. workdir_container_path is
the one exception — it's the container-side path used by
_validate_and_copy_output, which runs in this process.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import socket
import threading
import uuid
from pathlib import Path

import pytest

from src.agents.mirror.build import BuildError, build_sdist
from src.agents.mirror.safe_tar import (
    SafeTarError,
    open_safe_tar,
    validate_member_names,
)
from src.agents.mirror.sdist_reader import (
    SdistReaderError,
    read_build_system_requires,
)
from src.config import settings
from tests.mirror.hostile import sdists


# ── orchestrator-side defenses (no Docker needed) ─────────────

def test_path_traversal_refused_by_safe_tar():
    """A `../` member is refused by validate_member_names before
    the pyproject lookup runs."""
    data = sdists.path_traversal_sdist()
    with pytest.raises(SdistReaderError) as exc:
        read_build_system_requires(data)
    assert exc.value.reason == "unsafe_tar_member"
    assert "traversal" in exc.value.detail.lower()


def test_absolute_path_refused_by_safe_tar():
    data = sdists.absolute_path_sdist()
    with pytest.raises(SdistReaderError) as exc:
        read_build_system_requires(data)
    assert exc.value.reason == "unsafe_tar_member"
    assert "absolute" in exc.value.detail.lower()


def test_absolute_symlink_refused_by_safe_tar():
    data = sdists.absolute_symlink_sdist()
    with pytest.raises(SdistReaderError) as exc:
        read_build_system_requires(data)
    assert exc.value.reason == "unsafe_tar_member"
    assert "symlink" in exc.value.detail.lower()


def test_gzip_bomb_refused_by_decompression_cap():
    """A gzip bomb is refused during decompression, before
    tarfile sees it."""
    data = sdists.gzip_bomb_sdist()
    with pytest.raises(SdistReaderError) as exc:
        read_build_system_requires(data)
    assert exc.value.reason == "decompressed_too_large"


# ── build container defenses (Docker required) ────────────────

@pytest.mark.requires_docker
@pytest.mark.asyncio
async def test_network_isolated(_assert_no_leaked_containers):
    """
    setup.py tries to reach a listener on the host. Under
    --network none, the connection fails, the wheel builds, and
    the listener sees zero connections.

    The setup.py catches the connection failure and exits zero
    (build succeeds). The listener assertion is what proves
    isolation held: if the connection had succeeded, setup.py
    would have exited 99 and the build would have failed —
    which the test would also catch, differently.
    """
    # Start a TCP listener on a free port.
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    connections: list[tuple[str, int]] = []

    def accept_loop():
        srv.settimeout(1.0)
        try:
            conn, addr = srv.accept()
            connections.append(addr)
            conn.close()
        except socket.timeout:
            pass

    t = threading.Thread(target=accept_loop, daemon=True)
    t.start()

    try:
        with _FixtureDir() as fx:
            fx.write_sdist(
                sdists.network_attack_sdist("host.docker.internal", port),
            )
            await fx.prefetch_setuptools()

            result = await build_sdist(
                sdist_path=fx.sdist_host,
                wheelhouse_dir=fx.wheelhouse_host,
                entrypoint_host_path=fx.entrypoint_host,
                workdir_host_path=fx.workdir_host,
                workdir_container_path=fx.workdir_container,
            )
            assert result.wheel_path.is_file()

            t.join(timeout=2.0)
            assert connections == [], (
                f"network isolation failed: listener saw {connections}. "
                f"The build container reached the host despite "
                f"--network none."
            )
    finally:
        srv.close()


@pytest.mark.requires_docker
@pytest.mark.asyncio
async def test_read_only_mounts_unchanged(_assert_no_leaked_containers):
    """
    setup.py tries to write to every :ro mount. All writes must
    fail; the host-side hashes of the mount contents must be
    unchanged after the build.

    This test proves mount immutability, not just that writes
    failed. A setup.py that catches the error still builds — so
    asserting "the build fails" would test nothing. The hash
    comparison is what proves the mounts were untouched.
    """
    sdist_bytes, _targets = sdists.read_only_attack_sdist()

    with _FixtureDir() as fx:
        fx.write_sdist(sdist_bytes)
        await fx.prefetch_setuptools()

        # Hash the mount contents before the build.
        pre_hashes = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [fx.sdist_host, fx.entrypoint_host]
            if p.is_file()
        }

        await build_sdist(
            sdist_path=fx.sdist_host,
            wheelhouse_dir=fx.wheelhouse_host,
            entrypoint_host_path=fx.entrypoint_host,
            workdir_host_path=fx.workdir_host,
            workdir_container_path=fx.workdir_container,
        )

        post_hashes = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [fx.sdist_host, fx.entrypoint_host]
            if p.is_file()
        }
        assert pre_hashes == post_hashes, (
            f"a :ro mount was modified. before={pre_hashes} "
            f"after={post_hashes}"
        )


@pytest.mark.requires_docker
@pytest.mark.asyncio
async def test_output_symlink_refused(_assert_no_leaked_containers):
    """A symlink in /build/out is refused with
    output_not_regular_file (or output_wheel_count if the wheel
    and symlink both landed, which is what the fixture produces)."""
    with _FixtureDir() as fx:
        fx.write_sdist(sdists.output_symlink_sdist())
        await fx.prefetch_setuptools()

        with pytest.raises(BuildError) as exc:
            await build_sdist(
                sdist_path=fx.sdist_host,
                wheelhouse_dir=fx.wheelhouse_host,
                entrypoint_host_path=fx.entrypoint_host,
                workdir_host_path=fx.workdir_host,
                workdir_container_path=fx.workdir_container,
            )
        # The entrypoint writes both a wheel and the symlink, so
        # /build/out has two entries. _validate_and_copy_output
        # refuses at the count check.
        assert exc.value.reason in (
            "output_wheel_count",
            "output_not_regular_file",
        )


@pytest.mark.requires_docker
@pytest.mark.asyncio
async def test_forged_stdout_refused(_assert_no_leaked_containers):
    """setup.py prints a forged success line then exits nonzero.
    The orchestrator must decide from the exit code, not stdout."""
    with _FixtureDir() as fx:
        fx.write_sdist(sdists.forged_success_sdist())
        await fx.prefetch_setuptools()

        with pytest.raises(BuildError) as exc:
            await build_sdist(
                sdist_path=fx.sdist_host,
                wheelhouse_dir=fx.wheelhouse_host,
                entrypoint_host_path=fx.entrypoint_host,
                workdir_host_path=fx.workdir_host,
                workdir_container_path=fx.workdir_container,
            )
        assert exc.value.reason == "build_failed"
        # The tail should contain our forged line, proving the
        # orchestrator saw it and refused anyway.
        assert (
            "ALL TESTS PASSED" in exc.value.detail
            or "forged" in exc.value.detail.lower()
        )


@pytest.mark.requires_docker
@pytest.mark.asyncio
async def test_hang_times_out_and_cleans_up(_assert_no_leaked_containers):
    """setup.py hangs. The build times out and the container is
    killed by name. No aegis-build-* container remains afterward
    (asserted by the _assert_no_leaked_containers fixture)."""
    with _FixtureDir() as fx:
        fx.write_sdist(sdists.hang_sdist())
        await fx.prefetch_setuptools()

        with pytest.raises(BuildError) as exc:
            await build_sdist(
                sdist_path=fx.sdist_host,
                wheelhouse_dir=fx.wheelhouse_host,
                entrypoint_host_path=fx.entrypoint_host,
                workdir_host_path=fx.workdir_host,
                workdir_container_path=fx.workdir_container,
                timeout_seconds=10,
            )
        assert exc.value.reason == "build_timeout"


# ── the fixture directory helper ─────────────────────────────

class _FixtureDir:
    """
    A unique per-test subdirectory under VERIFIER_CONTAINER_WORKDIR,
    with both container-side and host-side paths for each input
    build_sdist needs.

    Lifecycle: `with _FixtureDir() as fx:` creates the directory
    on enter, removes it on exit (best-effort). Each test gets its
    own subdirectory keyed by uuid4, so concurrent test runs don't
    collide.

    Two-namespace split:

      sdist_container    /verifier-workdir/<uuid>/source.tar.gz
      sdist_host         /Users/.../verifier-workdir/<uuid>/source.tar.gz

    build_sdist's -v arguments use the HOST paths. The container
    paths are used by this process for file operations (write,
    mkdir) and by _validate_and_copy_output.
    """

    def __init__(self):
        self.uuid = uuid.uuid4().hex[:12]
        self.container_dir = (
            Path(settings.VERIFIER_CONTAINER_WORKDIR) / f"hostile-{self.uuid}"
        )
        self.host_dir = (
            Path(settings.VERIFIER_HOST_WORKDIR) / f"hostile-{self.uuid}"
        )

    def __enter__(self):
        self.container_dir.mkdir(parents=True, exist_ok=True)
        # Host dir mirrors the container dir; both exist because
        # VERIFIER_CONTAINER_WORKDIR is bind-mounted from
        # VERIFIER_HOST_WORKDIR. The mkdir above creates both.
        return self

    def __exit__(self, *exc_info):
        # Best-effort cleanup. A failed rmtree is a warning, not
        # a test failure — the container's own cleanup logic has
        # already removed the build's temp dirs by now.
        try:
            shutil.rmtree(self.container_dir, ignore_errors=True)
        except Exception:
            pass
        return False

    # ── paths ──────────────────────────────────────────────────

    @property
    def sdist_container(self) -> Path:
        return self.container_dir / "source.tar.gz"

    @property
    def sdist_host(self) -> Path:
        return self.host_dir / "source.tar.gz"

    @property
    def wheelhouse_container(self) -> Path:
        return self.container_dir / "wheelhouse"

    @property
    def wheelhouse_host(self) -> Path:
        return self.host_dir / "wheelhouse"

    @property
    def workdir_container(self) -> Path:
        return self.container_dir / "build"

    @property
    def workdir_host(self) -> Path:
        return self.host_dir / "build"

    @property
    def entrypoint_container(self) -> Path:
        return self.container_dir / ".build_entrypoint.py"

    @property
    def entrypoint_host(self) -> Path:
        return self.host_dir / ".build_entrypoint.py"

    # ── staging ────────────────────────────────────────────────

    def write_sdist(self, sdist_bytes: bytes) -> None:
        self.sdist_container.write_bytes(sdist_bytes)

    async def prefetch_setuptools(self) -> None:
        """Populate the wheelhouse with setuptools so the build
        can run offline."""
        from src.agents.mirror.integrate import _ensure_wheelhouse
        from src.agents.mirror.types import (
            BuildRequirement, ResolvedRequirement,
        )

        self.wheelhouse_container.mkdir(parents=True, exist_ok=True)
        await _ensure_wheelhouse(
            self.wheelhouse_container,
            [ResolvedRequirement(
                name="setuptools", version="68.2.2",
                filename="setuptools-68.2.2-py3-none-any.whl",
                sha256="",
                upload_time="2023-08-01T00:00:00Z",
                source_index="https://pypi.org/simple/",
                requested=BuildRequirement(
                    name="setuptools", specifier=">=40.8.0",
                    source="default", raw_line="setuptools>=40.8.0",
                ),
            )],
        )

        # Stage the build entrypoint. It has to be readable by
        # the daemon, which resolves the -v argument against the
        # host. Copy it into the container dir (which is
        # visible at the same relative path on the host) and use
        # the host path in build_sdist.
        shutil.copy2(
            "/app/scripts/build_entrypoint.py",
            self.entrypoint_container,
        )
        assert self.entrypoint_container.is_file()
        assert self.entrypoint_container.stat().st_size > 0

        # Create the build workdir and its /out subdirectory.
        self.workdir_container.mkdir()
        (self.workdir_container / "out").mkdir()
