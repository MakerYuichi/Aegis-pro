"""
Build hostile sdists.

Each function returns the bytes of a gzipped tarball that
contains exactly one attack. The tests in test_hostile_sdists.py
assert that the pipeline refuses each one with a specific
reason — not "fails somehow", but "fails with this named
reason."

The fixtures are grouped by which defense they exercise:

  - network.py — setup.py tries to reach the network
  - read_only.py — setup.py tries to modify read-only mounts
  - output.py — setup.py leaves something hostile in /build/out
  - forged.py — setup.py tries to fool the orchestrator with
    forged stdout
  - hang.py — setup.py runs forever
  - tar_members.py — the tarball has a malicious member name

The sdist format is a gzipped tar. Every fixture is a valid
tarball at the tar level — the attacks are in what the tarball
contains and what the setup.py does, not in the tar structure
itself.
"""
from __future__ import annotations

import io
import tarfile


def _tar_gz(members: dict[str, bytes]) -> bytes:
    """Build a gzipped tar with the given member paths/contents."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


# ── 1. network attack ──────────────────────────────────────────

def network_attack_sdist(host: str, port: int) -> bytes:
    """
    setup.py tries to reach (host, port) via TCP. If the connection
    succeeds, setup.py exits nonzero — that's a signal that the
    sandbox leaked network. If the connection fails (which it must
    under --network none), setup.py exits zero and a valid wheel is
    built.

    The test runs a listener on (host, port) on the test host and
    asserts the listener saw zero connections after the build.

    Why use an IP-shaped host: `host.docker.internal` under Docker
    Desktop resolves to the host's bridge IP. `--add-host
    host.docker.internal:host-gateway` in _build_argv makes it
    resolvable inside the container. If the fixture used
    `127.0.0.1`, it would resolve to the container's own loopback,
    not the host's — a connection to the container's own loopback
    would succeed trivially and the test would prove nothing.

    setup.py uses socket.socket().connect() directly, not a
    DNS-dependent client. That isolates the network-isolation claim
    from DNS resolution: even if the hostname fails to resolve, the
    test would fail differently, and the assertion would notice.
    """
    setup_py = f'''
import socket
import setuptools

def _try_network():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(("{host}", {port}))
        s.close()
        return True
    except (socket.error, OSError):
        return False

# If the network is reachable, exit nonzero so the build fails
# and the test can see the leak. If it's not reachable (which is
# the correct behavior), build the wheel normally.
if _try_network():
    raise SystemExit(99)

setuptools.setup(
    name="aegis-hostile-network",
    version="0.0.1",
    packages=[],
    py_modules=[],
)
'''

    # A minimal valid setup.py that builds an empty wheel.
    return _tar_gz({
        "aegis-hostile-network-0.0.1/setup.py":
            setup_py.encode("utf-8"),
        "aegis-hostile-network-0.0.1/PKG-INFO":
            b"Metadata-Version: 2.1\n"
            b"Name: aegis-hostile-network\n"
            b"Version: 0.0.1\n",
    })


# ── 2. read-only mount attack ─────────────────────────────────

def read_only_attack_sdist() -> tuple[bytes, list[str]]:
    """
    setup.py tries to write to several `:ro` mounts.

    Returns (tarball_bytes, list_of_target_paths).

    The test asserts:
      - The build succeeds (setup.py catches the write failures)
      - The host-side hashes of every mount in
        list_of_target_paths are unchanged after the build
    """
    setup_py = '''
import os
import setuptools

# Try to write to the read-only mounts. The build container has
# --read-only and each of these is a :ro bind mount, so every
# write must fail with PermissionError or OSError. We catch
# those and continue — the wheel still needs to build so the
# test can assert that the mount contents are unchanged.
_targets = [
    "/build/source.tar.gz",
    "/wheelhouse/_attack.txt",
    "/opt/build_entrypoint.py",
]

for target in _targets:
    try:
        with open(target, "a") as f:
            f.write("attacked")
    except (PermissionError, OSError):
        pass

setuptools.setup(
    name="aegis-hostile-read-only",
    version="0.0.1",
    packages=[],
    py_modules=[],
)
'''

    targets = [
        "/build/source.tar.gz",
        "/wheelhouse/_attack.txt",
        "/opt/build_entrypoint.py",
    ]

    data = _tar_gz({
        "aegis-hostile-read-only-0.0.1/setup.py":
            setup_py.encode("utf-8"),
        "aegis-hostile-read-only-0.0.1/PKG-INFO":
            b"Metadata-Version: 2.1\n"
            b"Name: aegis-hostile-read-only\n"
            b"Version: 0.0.1\n",
    })
    return data, targets


# ── 3. output symlink attack ──────────────────────────────────

def output_symlink_sdist() -> bytes:
    """
    setup.py leaves a symlink in /build/out pointing at a host
    file. The orchestrator's lstat + regular-file check refuses
    it with `output_not_regular_file` (or `output_wheel_count` if
    the wheel and symlink both landed).

    pip wheel runs setup.py twice: once to build the wheel, once
    to clean up. The second run would see the symlink it planted
    in the first run and fail with FileExistsError, aborting the
    build before the orchestrator's validation runs. The fixture
    swallows FileExistsError so the build succeeds and the
    defense has something to refuse.

    Without this, the fixture tests pip's tolerance for a failing
    setup.py clean, not the orchestrator's output validation.
    """
    setup_py = '''
import os
import setuptools

setuptools.setup(
    name="aegis-hostile-symlink",
    version="0.0.1",
    packages=[],
    py_modules=[],
)

try:
    os.symlink("/etc/passwd", "/build/out/attack_link")
except FileExistsError:
    pass
'''
    return _tar_gz({
        "aegis-hostile-symlink-0.0.1/setup.py":
            setup_py.encode("utf-8"),
        "aegis-hostile-symlink-0.0.1/PKG-INFO":
            b"Metadata-Version: 2.1\n"
            b"Name: aegis-hostile-symlink\n"
            b"Version: 0.0.1\n",
    })

# ── 4. forged success attack ──────────────────────────────────

def forged_success_sdist() -> bytes:
    """
    setup.py prints a forged "passed" line to stdout, then exits
    nonzero without building a wheel. The orchestrator must
    decide from the exit code and the presence of a validated
    wheel, not from stdout.

    Expected: build_failed (because /build/out is empty).
    """
    setup_py = '''
import sys
import setuptools

# Print a line that looks like a receipt and a message that
# looks like a success. Then exit nonzero without building
# anything — no wheel ends up in /build/out.
print("ALL TESTS PASSED")
print('{"status":"ok","wheel":"fake-0.0.1-py3-none-any.whl"}')
sys.exit(1)
'''
    return _tar_gz({
        "aegis-hostile-forged-0.0.1/setup.py":
            setup_py.encode("utf-8"),
        "aegis-hostile-forged-0.0.1/PKG-INFO":
            b"Metadata-Version: 2.1\n"
            b"Name: aegis-hostile-forged\n"
            b"Version: 0.0.1\n",
    })


# ── 5. hang attack ────────────────────────────────────────────

def hang_sdist() -> bytes:
    """
    setup.py runs an infinite loop. The build times out at
    BUILD_CONTAINER_TIMEOUT_SECONDS and the container is killed
    by name.

    The test asserts:
      - The build raises BuildError with reason="build_timeout"
      - No container named aegis-build-* remains after the call
    """
    setup_py = '''
import time
import setuptools

while True:
    time.sleep(1)
'''
    return _tar_gz({
        "aegis-hostile-hang-0.0.1/setup.py":
            setup_py.encode("utf-8"),
        "aegis-hostile-hang-0.0.1/PKG-INFO":
            b"Metadata-Version: 2.1\n"
            b"Name: aegis-hostile-hang\n"
            b"Version: 0.0.1\n",
    })


# ── 6. malicious tar members ──────────────────────────────────

def _tar_gz_with_member(
    member_name: str,
    content: bytes = b"content",
    *,
    extra_members: dict[str, bytes] | None = None,
) -> bytes:
    """Build a tar.gz with one member having a specific name."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in (extra_members or {}).items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        info = tarfile.TarInfo(name=member_name)
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def path_traversal_sdist() -> bytes:
    """The sdist contains a `../evil.py` member.

    Expected: read_build_system_requires raises
    SdistReaderError('unsafe_tar_member') — the orchestrator's
    pre-scan refuses the tarball before the build runs.
    """
    return _tar_gz_with_member(
        "../evil.py",
        b"# outside the extraction root",
        extra_members={
            "pkg-0.0.1/setup.py":
                b"import setuptools; setuptools.setup(name='pkg', version='0.0.1')",
        },
    )


def absolute_path_sdist() -> bytes:
    """The sdist contains an absolute path member.

    Expected: read_build_system_requires raises
    SdistReaderError('unsafe_tar_member').
    """
    return _tar_gz_with_member(
        "/etc/attack.conf",
        b"# outside the extraction root",
        extra_members={
            "pkg-0.0.1/setup.py":
                b"import setuptools; setuptools.setup(name='pkg', version='0.0.1')",
        },
    )


def absolute_symlink_sdist() -> bytes:
    """The sdist contains a symlink to /etc/passwd.

    Expected: read_build_system_requires raises
    SdistReaderError('unsafe_tar_member').
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        setup = b"import setuptools; setuptools.setup(name='pkg', version='0.0.1')"
        info = tarfile.TarInfo(name="pkg-0.0.1/setup.py")
        info.size = len(setup)
        tf.addfile(info, io.BytesIO(setup))

        link = tarfile.TarInfo(name="pkg-0.0.1/attack_link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tf.addfile(link)
    return buf.getvalue()


# ── 7. gzip bomb ──────────────────────────────────────────────

def gzip_bomb_sdist(
    *,
    decompressed_size: int = 600 * 1024 * 1024,  # 600 MB > 500 MB cap
) -> bytes:
    """
    An sdist whose single member decompresses to `decompressed_size`
    bytes of zeros. The compressed form is small (zeros compress
    extremely well) but the decompressed size exceeds
    BUILD_RESOLVER_MAX_DECOMPRESSED_BYTES.

    Expected: read_build_system_requires raises
    SdistReaderError('decompressed_too_large').

    The fixture writes zeros in 1MB chunks to avoid holding the
    whole 600MB decompressed in memory during construction — but
    the *test host* does hold the compressed form (small) and the
    decompressor reads it in 64KB chunks, so peak memory is
    bounded by the orchestrator's own decompression cap.

    Note: a real DEFLATE bomb is larger than 1KB — 600MB of zeros
    compresses to roughly 600KB. That's still far under
    BUILD_RESOLVER_MAX_SDIST_BYTES (200MB compressed cap), so the
    fetch succeeds; the bomb is caught by the decompression cap,
    which is what the test exercises.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="pkg-0.0.1/big.bin")
        info.size = decompressed_size
        # Stream zeros through tarfile in chunks.
        chunk = b"\x00" * (1024 * 1024)
        remaining = decompressed_size
        class _ZeroReader:
            def read(self, n):
                nonlocal remaining
                if remaining <= 0:
                    return b""
                take = min(n, remaining, len(chunk))
                remaining -= take
                return chunk[:take]
        tf.addfile(info, _ZeroReader())
    return buf.getvalue()
