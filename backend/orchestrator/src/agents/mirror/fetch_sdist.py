"""
Fetch an sdist from files.pythonhosted.org and verify its hash.

The download runs in the orchestrator process, but the resulting
bytes are never executed here. They're handed to the build
container as a read-only file mount. The orchestrator's job is to
verify identity: the sha256 of the downloaded bytes must equal
what PyPI's JSON advertised for that file.

Boundary checks:
  - Only files.pythonhosted.org hosts are allowed.
  - Only https is allowed.
  - The download is streamed with a cap equal to the size PyPI's
    JSON declares for the file. No declared size means the whole
    thing is capped at settings.BUILD_RESOLVER_MAX_SDIST_BYTES.

Streaming with a declared-size cap does two things: it fails fast
on a lying server (a 100-byte file that starts streaming a
gigabyte), and it prevents the orchestrator from buffering an
arbitrary amount before the hash check.
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

    Streams the download with a cap. Raises SdistFetchError on any
    failure. Never returns unverified bytes — the hash check is
    not optional.
    """
    _assert_allowed_host(ref.url)

    # The cap is the smaller of the declared size (if any) and the
    # configured maximum. A declared-size cap fails fast if the
    # server starts streaming more than it advertised.
    configured_max = settings.BUILD_RESOLVER_MAX_SDIST_BYTES
    declared = ref.size_bytes if hasattr(ref, "size_bytes") else None
    cap = min(
        declared if declared and declared > 0 else configured_max,
        configured_max,
    )

    req = urllib.request.Request(
        ref.url,
        headers={"User-Agent": settings.BUILD_RESOLVER_USER_AGENT},
    )

    try:
        with urllib.request.urlopen(
            req, timeout=settings.BUILD_RESOLVER_TIMEOUT_SECONDS,
        ) as resp:
            buf = bytearray()
            chunk_size = 64 * 1024
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                buf.extend(chunk)
                if len(buf) > cap:
                    raise SdistFetchError(
                        "sdist_too_large",
                        f"{len(buf)} bytes > {cap} "
                        f"(declared: {declared}, "
                        f"configured: {configured_max})",
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
        raise SdistFetchError("sdist_url_not_https", url)
    if parsed.hostname not in ALLOWED_SDIST_HOSTS:
        raise SdistFetchError(
            "sdist_url_host_not_allowed",
            f"{parsed.hostname!r} not in "
            f"{sorted(ALLOWED_SDIST_HOSTS)}",
        )
