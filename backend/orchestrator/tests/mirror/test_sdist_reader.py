"""
Tests for src.agents.mirror.sdist_reader.

Uses in-memory tarballs built with tarfile, so no disk I/O and no
fixture files. Each test constructs exactly the tarball shape it
needs.
"""
from __future__ import annotations

import io
import tarfile

import pytest

from src.agents.mirror.sdist_reader import (
    MAX_MEMBER_BYTES,
    SdistReaderError,
    read_build_system_requires,
)


def _make_tarball(members: dict[str, bytes]) -> bytes:
    """Build an in-memory tar with the given member paths/contents."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _make_tarball_with_symlink(
    target: str, link_name: str, extra: dict[str, bytes] | None = None,
) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in (extra or {}).items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
        link = tarfile.TarInfo(name=link_name)
        link.type = tarfile.SYMTYPE
        link.linkname = target
        tf.addfile(link)
    return buf.getvalue()


# ── happy paths ─────────────────────────────────────────────────

def test_reads_pyproject_build_requires():
    pyproject = (
        b"[build-system]\n"
        b'requires = ["setuptools>=40.8.0", "wheel"]\n'
        b'build-backend = "setuptools.build_meta"\n'
    )
    data = _make_tarball({
        "pkg-1.0/pyproject.toml": pyproject,
        "pkg-1.0/setup.py": b"# legacy",
    })
    reqs = read_build_system_requires(data)
    assert [r.name for r in reqs] == ["setuptools", "wheel"]
    assert reqs[0].specifier == ">=40.8.0"
    assert reqs[0].source == "pyproject"
    assert reqs[1].specifier == ""


def test_reads_pyproject_with_extras():
    pyproject = (
        b"[build-system]\n"
        b'requires = ["cython[build]>=0.29", "numpy<3"]\n'
    )
    data = _make_tarball({"pkg-1.0/pyproject.toml": pyproject})
    reqs = read_build_system_requires(data)
    assert [r.name for r in reqs] == ["cython", "numpy"]
    assert reqs[0].specifier == ">=0.29"
    assert reqs[1].specifier == "<3"


def test_no_pyproject_returns_empty():
    data = _make_tarball({
        "pkg-1.0/setup.py": b"from setuptools import setup",
        "pkg-1.0/PKG-INFO": b"Name: pkg",
    })
    assert read_build_system_requires(data) == []


def test_pyproject_without_build_system_returns_empty():
    pyproject = b"[project]\nname = 'x'\nversion = '1.0'\n"
    data = _make_tarball({"pkg-1.0/pyproject.toml": pyproject})
    assert read_build_system_requires(data) == []


def test_pyproject_without_requires_returns_empty():
    pyproject = (
        b"[build-system]\n"
        b'build-backend = "setuptools.build_meta"\n'
    )
    data = _make_tarball({"pkg-1.0/pyproject.toml": pyproject})
    assert read_build_system_requires(data) == []


# ── bounds and safety ───────────────────────────────────────────

def test_pyproject_at_depth_1_ignored():
    """Only `<root>/pyproject.toml` is read. A pyproject nested
    deeper is a vendored copy, not the sdist's own."""
    pyproject = b"[build-system]\nrequires = ['setuptools']\n"
    data = _make_tarball({
        "pkg-1.0/vendor/inner/pyproject.toml": pyproject,
        "pkg-1.0/setup.py": b"",
    })
    assert read_build_system_requires(data) == []


def test_pyproject_too_large_raises():
    pyproject = b"x" * (MAX_MEMBER_BYTES + 100)
    data = _make_tarball({"pkg-1.0/pyproject.toml": pyproject})
    with pytest.raises(SdistReaderError) as exc_info:
        read_build_system_requires(data)
    assert exc_info.value.reason == "pyproject_too_large"


def test_malformed_toml_returns_empty_not_raises():
    pyproject = b"[build-system\n"  # missing closing bracket
    data = _make_tarball({"pkg-1.0/pyproject.toml": pyproject})
    # Malformed pyproject is not fatal — caller falls back to
    # pip's default.
    assert read_build_system_requires(data) == []


def test_non_utf8_pyproject_returns_empty():
    pyproject = b"[build-system]\nrequires = ['\xff\xfe']\n"
    data = _make_tarball({"pkg-1.0/pyproject.toml": pyproject})
    assert read_build_system_requires(data) == []


def test_not_a_tarball_raises():
    with pytest.raises(SdistReaderError) as exc_info:
        read_build_system_requires(b"not a tarball")
    assert exc_info.value.reason == "not_a_tarball"


def test_absolute_symlinked_pyproject_refused():
    """A symlink pointing outside the package is refused outright.

    validate_member_names runs before the pyproject lookup, so an
    absolute symlink anywhere in the tarball — even one that isn't
    the pyproject — gets the whole tarball refused. That's stricter
    than skipping the pyproject; it's correct, because a tarball
    that carries an absolute symlink is hostile.
    """
    data = _make_tarball_with_symlink(
        target="/etc/passwd",
        link_name="pkg-1.0/pyproject.toml",
    )
    with pytest.raises(SdistReaderError) as exc_info:
        read_build_system_requires(data)
    assert exc_info.value.reason == "unsafe_tar_member"
    assert "/etc/passwd" in exc_info.value.detail


def test_relative_symlinked_pyproject_ignored():
    """A symlink with a relative target inside the package is
    allowed by validate_member_names. The reader skips it because
    member.isfile() is False for symlinks — reading through would
    follow the link to the target file, and a symlinked
    pyproject.toml is not the sdist's real pyproject."""
    data = _make_tarball_with_symlink(
        target="real_setup.py",
        link_name="pkg-1.0/pyproject.toml",
        extra={"pkg-1.0/real_setup.py": b"# real setup"},
    )
    assert read_build_system_requires(data) == []


def test_unparseable_requirement_skipped():
    pyproject = (
        b"[build-system]\n"
        b'requires = ["setuptools", "!!!invalid!!!", "wheel"]\n'
    )
    data = _make_tarball({"pkg-1.0/pyproject.toml": pyproject})
    reqs = read_build_system_requires(data)
    # The two valid requirements survive; the bad one is dropped.
    assert [r.name for r in reqs] == ["setuptools", "wheel"]
