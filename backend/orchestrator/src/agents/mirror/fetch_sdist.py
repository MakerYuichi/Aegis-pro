"""
Fetch an sdist from files.pythonhosted.org and verify its hash.

The download runs in the orchestrator process, but the resulting
bytes are never executed here. They're handed to the build
container as a read-only file mount. The orchestrator's job is to
verify identity: the sha256 of the downloaded bytes must equal
what PyPI's JSON advertised for that file.

Boundary check: this module refuses any URL that isn't on
files.pythonhosted.org. The URL comes from PyPI's JSON, which is
trusted, but defense-in-depth — if the JSON were ever tampered
with in transit, a files.pythonhosted.org-only check prevents an
arbitrary-URL fetch.
"""
from __future__ import annotations

import hashlib
import urllib.error
import urllib.parse
import urllib.request

from loguru import logger

from src.agents.mirror.types import SdistRef
from src.config import settings


ALLOWED_SDIST_HOSTS = frozenset({
    "files.pythonhosted.org",
})


class SdistFetchError(Exception):
    """Infrastructure failure — network, size cap, hash mismatch.
    Never a policy failure; those don't reach this module."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def fetch_sdist(ref: SdistRef) -> bytes:
    """
    Download the sdist and return its bytes, verified against
    ref.sha256.

    Raises SdistFetchError on any failure. Never returns unverified
    bytes — the hash check is not optional.
    """
    _assert_allowed_host(ref.url)

    max_bytes = settings.BUILD_RESOLVER_MAX_SDIST_BYTES
    req = urllib.request.Request(
        ref.url,
        headers={"User-Agent": settings.BUILD_RESOLVER_USER_AGENT},
    )
    try:
        with urllib.request.urlopen(
            req, timeout=settings.BUILD_RESOLVER_TIMEOUT_SECONDS,
        ) as resp:
            # Read incrementally to enforce the size cap before the
            # whole tarball is in memory.
            buf = bytearray()
            chunk_size = 64 * 1024
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise SdistFetchError(
                        "sdist_too_large",
                        f"{len(buf)} bytes > {max_bytes}",
                    )
    except urllib.error.HTTPError as e:
        raise SdistFetchError(
            "sdist_fetch_failed", f"HTTP {e.code} for {ref.url}",
        ) from e
    except urllib.error.URLError as e:
        raise SdistFetchError(
            "sdist_fetch_failed",
            f"{type(e).__name__}: {e}",
        ) from e

    data = bytes(buf)
    actual = "sha256:" + hashlib.sha256(data).hexdigest()
    if actual != ref.sha256:
        raise SdistFetchError(
            "sdist_hash_mismatch",
            f"expected {ref.sha256}, got {actual}",
        )

    logger.info(
        f"sdist_fetch: {ref.filename} "
        f"({len(data)} bytes, sha256 verified)"
    )
    return data


def _assert_allowed_host(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise SdistFetchError(
            "sdist_url_not_https", url,
        )
    if parsed.hostname not in ALLOWED_SDIST_HOSTS:
        raise SdistFetchError(
            "sdist_url_host_not_allowed",
            f"{parsed.hostname!r} not in {sorted(ALLOWED_SDIST_HOSTS)}",
        )
