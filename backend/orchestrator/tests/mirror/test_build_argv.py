"""
Tests for _build_argv. Verifies the shape of the docker run
command that spawns the build container.

The specific bug this suite prevents: a "-m" flag accidentally
inserted between "python" and the entrypoint path. That makes
Python treat the path as a module name, and the container fails
with "can't find '__main__' module" — a message that points at
the file, not the flag.
"""
from pathlib import Path

from src.agents.mirror.build import _build_argv


def _call():
    return _build_argv(
        container_name="aegis-build-test",
        sdist_host=Path("/host/sdist.tar.gz"),
        wheelhouse_host=Path("/host/wheelhouse"),
        entrypoint_host=Path("/host/.build_entrypoint.py"),
        out_host=Path("/host/out"),
    )


def test_command_is_python_then_script_path():
    """The command after the image is `python <script>`, NOT
    `python -m <script>`. The -m flag would make Python treat the
    path as a module name."""
    argv = _call()
    # Find the image name and check what follows.
    image = "aegis-builder:latest"
    if image not in argv:
        # Fall back to config check via the tail.
        tail = argv[-4:]
    else:
        idx = argv.index(image)
        tail = argv[idx + 1:]

    assert tail[0] == "python", (
        f"first arg after image should be 'python', got {tail[0]!r}. "
        f"Full tail: {tail}"
    )
    assert tail[1] == "/opt/build_entrypoint.py", (
        f"second arg after python should be the script path, "
        f"got {tail[1]!r}. If it's '-m', that's the bug."
    )
    # Explicitly refuse the -m mistake.
    assert tail[0] != "-m" and tail[1] != "-m", (
        "the command must not use -m between python and the script path"
    )


def test_entrypoint_mount_is_read_only():
    argv = _call()
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    entrypoint_mount = next(
        (m for m in mounts if m.endswith(":/opt/build_entrypoint.py:ro")),
        None,
    )
    assert entrypoint_mount is not None, (
        f"no read-only mount for /opt/build_entrypoint.py. "
        f"mounts: {mounts}"
    )


def test_out_dir_mount_is_read_write():
    argv = _call()
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    # The mount spec is "<host_path>:/build/out:rw". Match on the
    # container path with its mount mode, not the bare path.
    out_mount = next(
        (m for m in mounts if m.endswith(":/build/out:rw")), None,
    )
    assert out_mount is not None, (
        f"no read-write mount for /build/out. mounts: {mounts}"
    )


def test_container_has_name():
    argv = _call()
    assert "--name" in argv
    idx = argv.index("--name")
    assert argv[idx + 1] == "aegis-build-test"
