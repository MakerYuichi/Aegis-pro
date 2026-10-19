"""
Tests for safe_tar.

Each test builds a tarball that exercises one bound:
  - decompressed bytes cap
  - member count cap
  - malicious member names (absolute path, traversal, unsafe symlink)
  - structurally corrupt tarballs
"""
from __future__ import annotations

import gzip
import io
import tarfile

import pytest

from src.agents.mirror.safe_tar import (
    SafeTarError,
    open_safe_tar,
    scan_member_count,
    validate_member_names,
)


def _make_tar(members: list[tuple[str, bytes]]) -> bytes:
    """Build a gzipped tar with the given (name, content).

    Production sdists arrive gzipped from PyPI. The test helper
    gzips too so the tests exercise the same code path.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in members:
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _make_targz(members: list[tuple[str, bytes]]) -> bytes:
    """Build a gzipped tar."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in members:
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _make_tar_with_symlink(
    base_members: list[tuple[str, bytes]],
    link_name: str,
    link_target: str,
) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in base_members:
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
        link = tarfile.TarInfo(name=link_name)
        link.type = tarfile.SYMTYPE
        link.linkname = link_target
        tf.addfile(link)
    return buf.getvalue()


# ── happy path ──────────────────────────────────────────────────

def test_open_safe_tar_reads_simple_tarball():
    data = _make_targz([("pkg-1.0/pyproject.toml", b"[build-system]\n")])
    tf, counter = open_safe_tar(data)
    with tf:
        names = [m.name for m in tf]
    assert names == ["pkg-1.0/pyproject.toml"]
    assert counter.total_read > 0


# ── decompression cap ───────────────────────────────────────────

def test_decompression_cap_fires_during_read():
    # 5 MB of zeros, then cap at 1 MB.
    payload = b"\x00" * (5 * 1024 * 1024)
    data = _make_targz([("pkg-1.0/big.bin", payload)])
    with pytest.raises(SafeTarError) as exc_info:
        open_safe_tar(data, max_decompressed_bytes=1024 * 1024)
    assert exc_info.value.reason == "decompressed_too_large"


def test_decompression_cap_allows_under_limit():
    payload = b"\x00" * (100 * 1024)  # 100 KB
    data = _make_targz([("pkg-1.0/small.bin", payload)])
    tf, _ = open_safe_tar(data, max_decompressed_bytes=1024 * 1024)
    with tf:
        _ = list(tf)  # exhaust
    # No exception means the read stayed under the cap.


# ── malformed tarballs ──────────────────────────────────────────

def test_not_a_tarball_raises():
    with pytest.raises(SafeTarError) as exc_info:
        open_safe_tar(b"this is not a tarball")
    assert exc_info.value.reason in (
        "not_a_tarball", "corrupt_tarball",
    )


def test_truncated_gzip_raises():
    data = _make_targz([("pkg-1.0/x", b"content" * 1000)])
    # Truncate the gzip stream mid-file.
    with pytest.raises(SafeTarError):
        open_safe_tar(data[:len(data) // 2])


# ── member count cap ───────────────────────────────────────────

def test_scan_member_count_fires_on_excess():
    data = _make_tar([(f"f{i}", b"") for i in range(50)])
    tf, _ = open_safe_tar(data)
    with tf:
        with pytest.raises(SafeTarError) as exc_info:
            scan_member_count(tf, max_members=10)
    assert exc_info.value.reason == "too_many_members"


def test_scan_member_count_allows_under_limit():
    data = _make_tar([(f"f{i}", b"") for i in range(5)])
    tf, _ = open_safe_tar(data)
    with tf:
        scan_member_count(tf, max_members=10)  # no raise


# ── member name validation ─────────────────────────────────────

def test_absolute_path_member_refused():
    data = _make_tar([("/etc/passwd", b"content")])
    tf, _ = open_safe_tar(data)
    with tf:
        with pytest.raises(SafeTarError) as exc_info:
            validate_member_names(tf)
    assert exc_info.value.reason == "unsafe_tar_member"
    assert "absolute" in exc_info.value.detail.lower()


def test_path_traversal_member_refused():
    data = _make_tar([("../evil.py", b"content")])
    tf, _ = open_safe_tar(data)
    with tf:
        with pytest.raises(SafeTarError) as exc_info:
            validate_member_names(tf)
    assert exc_info.value.reason == "unsafe_tar_member"
    assert "traversal" in exc_info.value.detail.lower()


def test_absolute_symlink_refused():
    data = _make_tar_with_symlink(
        base_members=[("pkg-1.0/x", b"content")],
        link_name="pkg-1.0/evil_link",
        link_target="/etc/passwd",
    )
    tf, _ = open_safe_tar(data)
    with tf:
        with pytest.raises(SafeTarError) as exc_info:
            validate_member_names(tf)
    assert "symlink" in exc_info.value.detail.lower()


def test_traversal_symlink_refused():
    data = _make_tar_with_symlink(
        base_members=[("pkg-1.0/x", b"content")],
        link_name="pkg-1.0/evil_link",
        link_target="../../etc/passwd",
    )
    tf, _ = open_safe_tar(data)
    with tf:
        with pytest.raises(SafeTarError) as exc_info:
            validate_member_names(tf)
    assert "symlink" in exc_info.value.detail.lower()


def test_safe_symlink_allowed():
    """A symlink inside the extraction root is legitimate."""
    data = _make_tar_with_symlink(
        base_members=[("pkg-1.0/real.py", b"content")],
        link_name="pkg-1.0/link.py",
        link_target="real.py",
    )
    tf, _ = open_safe_tar(data)
    with tf:
        validate_member_names(tf)  # no raise
