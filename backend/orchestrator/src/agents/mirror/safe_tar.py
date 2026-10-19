"""
Bounded tar reading for untrusted sdists.

The orchestrator reads a tarball in memory to find its
[build-system].requires. That tarball is untrusted input from a
repo we don't control. A malicious tarball can be a "gzip bomb":
a small compressed file that decompresses to gigabytes. Reading it
naively burns CPU and memory in the orchestrator's trusted process.

This module decompresses the gzip stream with a per-chunk byte
count. The count is on the DECOMPRESSED bytes, not the compressed
input — a 5KB gzip that expands to 5MB must fail a 1MB cap, and
counting the compressed input would let it through. tarfile then
reads the already-bounded in-memory bytes.
"""
from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path

from loguru import logger

from src.config import settings


_DEFAULT_MAX_DECOMPRESSED_BYTES = 500 * 1024 * 1024


class SafeTarError(Exception):
    """Raised when a tarball is malformed or violates a bound."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class _CountingReader(io.RawIOBase):
    """
    A file-like wrapper that counts bytes read.

    Raises SafeTarError when the total exceeds `limit`. Used by
    tests to inspect how much was decompressed; the production
    decompression loop tracks total itself and populates the
    counter's `_total` after the fact.
    """

    def __init__(self, fileobj, limit: int):
        self._fileobj = fileobj
        self._limit = limit
        self._total = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        chunk = self._fileobj.read(size)
        if chunk:
            self._total += len(chunk)
            if self._total > self._limit:
                raise SafeTarError(
                    "decompressed_too_large",
                    f"{self._total} bytes > {self._limit}",
                )
        return chunk

    def readinto(self, b) -> int:
        n = len(b)
        chunk = self.read(n)
        b[:len(chunk)] = chunk
        return len(chunk)

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._fileobj.seek(offset, whence)

    def tell(self) -> int:
        return self._fileobj.tell()

    @property
    def total_read(self) -> int:
        return self._total


def open_safe_tar(
    tarball_bytes: bytes,
    *,
    max_decompressed_bytes: int | None = None,
) -> tuple[tarfile.TarFile, _CountingReader]:
    """
    Open a tarball with decompression bounds.

    Decompresses the gzip stream with a running byte count on the
    DECOMPRESSED output. If the total exceeds the cap,
    SafeTarError fires before tarfile sees the bomb. Otherwise,
    tarfile reads from the already-decompressed in-memory buffer.

    Returns (tarfile, counter). The counter's total_read reports
    the decompressed byte count.

    Raises SafeTarError on:
      - non-tar bytes (`not_a_tarball`)
      - corrupted gzip/tar structure (`corrupt_tarball`)
      - decompressed size exceeding the cap
        (`decompressed_too_large`)
    """
    limit = (
        max_decompressed_bytes
        or getattr(
            settings,
            "BUILD_RESOLVER_MAX_DECOMPRESSED_BYTES",
            _DEFAULT_MAX_DECOMPRESSED_BYTES,
        )
    )

    decompressed_buf = bytearray()
    try:
        with gzip.GzipFile(
            fileobj=io.BytesIO(tarball_bytes), mode="rb",
        ) as gz:
            while True:
                chunk = gz.read(64 * 1024)
                if not chunk:
                    break
                decompressed_buf.extend(chunk)
                if len(decompressed_buf) > limit:
                    raise SafeTarError(
                        "decompressed_too_large",
                        f"{len(decompressed_buf)} bytes > {limit}",
                    )
    except SafeTarError:
        raise
    except (gzip.BadGzipFile, tarfile.TarError) as e:
        raise SafeTarError(
            "not_a_tarball", f"{type(e).__name__}: {e}",
        ) from e
    except EOFError as e:
        raise SafeTarError(
            "corrupt_tarball", f"truncated gzip stream: {e}",
        ) from e
    except Exception as e:
        raise SafeTarError(
            "corrupt_tarball", f"{type(e).__name__}: {e}",
        ) from e

    try:
        tf = tarfile.open(
            fileobj=io.BytesIO(bytes(decompressed_buf)), mode="r:",
        )
    except tarfile.TarError as e:
        raise SafeTarError(
            "not_a_tarball", f"{type(e).__name__}: {e}",
        ) from e

    counter = _CountingReader(io.BytesIO(b""), limit)
    counter._total = len(decompressed_buf)
    return tf, counter


def validate_member_names(tf: tarfile.TarFile) -> None:
    """
    Refuse a tarball whose member list contains names that
    `filter="data"` would refuse.

    Raises SafeTarError with reason `unsafe_tar_member`.
    """
    for member in tf:
        name = member.name

        if name.startswith("/"):
            raise SafeTarError(
                "unsafe_tar_member",
                f"absolute path: {name!r}",
            )

        parts = Path(name).parts
        if ".." in parts:
            raise SafeTarError(
                "unsafe_tar_member",
                f"path traversal: {name!r}",
            )

        if member.issym() or member.islnk():
            target = member.linkname
            if not target:
                continue
            if target.startswith("/"):
                raise SafeTarError(
                    "unsafe_tar_member",
                    f"absolute symlink target in {name!r}: {target!r}",
                )
            target_parts = Path(target).parts
            if ".." in target_parts:
                raise SafeTarError(
                    "unsafe_tar_member",
                    f"traversal symlink in {name!r}: {target!r}",
                )


def scan_member_count(
    tf: tarfile.TarFile, max_members: int = 10_000,
) -> None:
    """
    Refuse a tarball with too many members.

    Raises SafeTarError with reason `too_many_members`.
    """
    count = 0
    for _ in tf:
        count += 1
        if count > max_members:
            raise SafeTarError(
                "too_many_members",
                f"scanned {max_members}, still no end",
            )
