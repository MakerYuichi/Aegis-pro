"""
Parse the prefetcher container's stdout into a structured receipt.

Contract with the container: the last non-empty line of stdout is a
single-line JSON object with the fields below. Anything before that
is pip output, which we log and discard. A missing or malformed last
line is itself information — the container crashed before it could
report — and maps to ReceiptError.

Design note: the container never writes the receipt to the shared
cache. The cache holds wheels, which are data the container fetched
from PyPI. The receipt is a claim about what was fetched; anything a
compromised install step could write to the volume is not something
the orchestrator should trust. So the container announces the
receipt on stdout, and the orchestrator is the one that durably
stores it.

Test-count extraction is deliberately NOT done here. This module
only parses the prefetcher's receipt, which is what the prefetcher
knows: the manifest hash, the resolved packages, the sources. The
test counts come later, from the verifier's output, and live in the
verification receipt that PR 2 writes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass


# Cap on how much of stdout we parse. pip can emit hundreds of
# kilobytes on a slow network. We only need the last line; anything
# longer than this and we assume the container is broken.
MAX_RECEIPT_LINE_BYTES = 256 * 1024


class ReceiptError(Exception):
    """Raised when the container's stdout doesn't end in a receipt."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True)
class PrefetchReceipt:
    """
    What the prefetcher container reports back.

    Fields:
        manifest_path:       "backend/orchestrator/requirements.txt",
                             relative to the repo root
        manifest_hash:       sha256 of the sanitized manifest content
        python_version:      "3.11.16" — the container's python
        platform_tag:        "linux_x86_64"
        packages:            list of resolved-package dicts, each:
                             {
                               "name": str,
                               "base_version": str,
                               "local_variant": str,
                               "extras": [str],
                               "environment_marker": str | None,
                               "hashes": [str],
                               "source_index": str,
                               "filename": str,
                               "dependencies": [str],
                             }
        fetched_now:         True when the prefetch actually downloaded
                             wheels; False when it found a warm cache
                             and skipped the network entirely
        duration_ms:         container wall-clock time
    """
    manifest_path: str
    manifest_hash: str
    python_version: str
    platform_tag: str
    packages: list[dict]
    fetched_now: bool
    duration_ms: int

@dataclass(frozen=True)
class PrefetchFailure:
    """
    Structured diagnosis of why the prefetcher couldn't fetch a
    package.

    reason is one of:
        "version_not_found"       — the version doesn't exist on PyPI
        "sdist_only"              — exists, ships only a source tarball
        "no_compatible_wheel"     — wheels exist, none for this Py/plat
        "pypi_lookup_failed"      — we couldn't ask PyPI (network/parse)
    """
    reason: str
    detail: str
    package: str
    version: str
    available_wheels: list[str]
    index_url: str


def parse_receipt(stdout: str) -> PrefetchReceipt:
    """
    Extract the receipt from the container's stdout.

    The receipt is the last non-empty line. Everything before it is
    pip output and is discarded here — the caller logs it.
    """
    if not stdout:
        raise ReceiptError("empty_stdout")

    lines = stdout.strip().splitlines()
    if not lines:
        raise ReceiptError("empty_stdout")

    last_line = lines[-1]
    if len(last_line.encode("utf-8")) > MAX_RECEIPT_LINE_BYTES:
        raise ReceiptError(
            "receipt_too_large",
            f"{len(last_line)} bytes > {MAX_RECEIPT_LINE_BYTES}",
        )

    try:
        payload = json.loads(last_line)
    except json.JSONDecodeError as e:
        raise ReceiptError(
            "receipt_not_json", f"{e.msg} at pos {e.pos}"
        ) from e

    if not isinstance(payload, dict):
        raise ReceiptError(
            "receipt_not_object", f"got {type(payload).__name__}"
        )

    required = (
        "manifest_path",
        "manifest_hash",
        "python_version",
        "platform_tag",
        "packages",
        "fetched_now",
        "duration_ms",
    )
    for key in required:
        if key not in payload:
            raise ReceiptError("receipt_missing_field", key)

    packages = payload["packages"]
    if not isinstance(packages, list):
        raise ReceiptError(
            "receipt_packages_not_list",
            f"got {type(packages).__name__}",
        )

    return PrefetchReceipt(
        manifest_path=str(payload["manifest_path"]),
        manifest_hash=str(payload["manifest_hash"]),
        python_version=str(payload["python_version"]),
        platform_tag=str(payload["platform_tag"]),
        packages=packages,
        fetched_now=bool(payload["fetched_now"]),
        duration_ms=int(payload["duration_ms"]),
    )


def parse_failure(stdout: str) -> PrefetchFailure | None:
    """
    If the container emitted a failure diagnosis as the last line
    of stdout, return it as a PrefetchFailure. Otherwise None.
    """
    if not stdout:
        return None
    lines = stdout.strip().splitlines()
    if not lines:
        return None
    last = lines[-1]
    try:
        payload = json.loads(last)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or "error" not in payload:
        return None
    return PrefetchFailure(
        reason=str(payload["error"]),
        detail=str(payload.get("detail", "")),
        package=str(payload.get("package", "")),
        version=str(payload.get("version", "")),
        available_wheels=list(payload.get("available_wheels", [])),
        index_url=str(payload.get("index_url", "")),
    )
