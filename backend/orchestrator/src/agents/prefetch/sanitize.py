"""
Sanitize a Python requirements manifest.

Rule, in one sentence: untrusted text is data, never arguments.

The manifest comes from a repo we don't trust. pip will happily obey
`--index-url`, `--find-links`, `pkg @ https://...`, `-e git+...`, and
`--extra-index-url` if we pass the file to it directly. It will also
execute a package's setup.py if the manifest resolves to an sdist.
Both are exactly what we're trying to prevent.

This module reads the manifest and produces a list of PackagePin
objects. Anything that is not a `name[extras]` followed by a valid
version specifier is rejected with a message naming the offending
line.

Ranges vs. pins
───────────────
Two forms are accepted:

  - Exact pin:   `fastapi==0.115.11`
                 `is_pinned=True`, `base_version="0.115.11"`
  - Range:       `uvicorn[standard]>=0.34.0`
                 `is_pinned=False`, `raw_specifier=">=0.34.0"`

Ranges are not rejected. They are preserved verbatim and passed
through to the prefetcher, where pip's own resolver picks the
absolute version. The resolver runs in the prefetcher container
(network yes, no secrets), and the resulting pins are recorded in
the receipt. The sanitizer does no network I/O and makes no
resolution decisions.

Local version variants (`torch==2.14.0+cpu`) are parsed into a
separate `local_variant` field. The variant is preserved precisely
so the policy router can send it to a non-PyPI index. Stripping the
suffix before routing would silently convert a CPU-only install
into a GPU download.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


class SanitizeError(Exception):
    """Raised when a manifest contains a line we won't pass to pip."""

    def __init__(self, reason: str, line_number: int, line_content: str):
        self.reason = reason
        self.line_number = line_number
        self.line_content = line_content
        super().__init__(
            f"{reason} at line {line_number}: {line_content!r}"
        )


@dataclass(frozen=True)
class PackagePin:
    """
    A single package requirement from the manifest.

    Two shapes:

      * Pinned   (`pkg==1.2.3`):
            is_pinned     = True
            base_version  = "1.2.3"
            local_variant = "" or "cpu"
            raw_specifier = "==1.2.3" (or "==1.2.3+cpu")

      * Unpinned (`pkg>=1.2.3` or `pkg`):
            is_pinned     = False
            base_version  = ""
            local_variant = ""
            raw_specifier = ">=1.2.3" (or "" when no operator)

    Fields:
        name:               PEP 503 normalized package name
        is_pinned:          True when `==` was used
        base_version:       version without local variant (pinned only)
        local_variant:      "cpu", "rocm", "" (pinned only)
        raw_specifier:      the operator+version as written, or "" when
                            the line had no operator. Preserved for the
                            prefetcher's lockfile rendering.
        extras:             ("standard",) for `uvicorn[standard]`
        environment_marker: "; python_version < '3.12'" — kept intact
        explicit_hashes:    from `--hash=` fragments (not yet wired)
        raw_line:           original line, for error messages
        line_number:        1-based line number in the manifest
    """
    name: str
    is_pinned: bool
    base_version: str
    local_variant: str
    raw_specifier: str
    extras: tuple[str, ...]
    environment_marker: str | None
    explicit_hashes: tuple[str, ...]
    raw_line: str
    line_number: int


# `name[extras][op version[+variant]] [; marker]`
#
# op is one of: == >= <= ~= != > < or nothing.
# We capture the op and version as a single `specifier` group for
# unpinned lines, and separately for pinned lines so we can split
# the local variant out.
_REQ_RE = re.compile(
    r"""
    ^\s*
    (?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)
    (?P<extras>\[[^\]]+\])?
    \s*
    (?:
        (?P<op>==|>=|<=|~=|!=|>|<)
        \s*
        (?P<version>[A-Za-z0-9][A-Za-z0-9._-]*)
        (?:\+(?P<variant>[A-Za-z0-9][A-Za-z0-9._-]*))?
    )?
    \s*
    (?:;\s*(?P<marker>.+?))?
    \s*$
    """,
    re.VERBOSE,
)

_STRIPPED_DIRECTIVES = (
    "--extra-index-url",
    "-i", "--index-url",
    "-f", "--find-links",
    "--trusted-host",
    "--pre",
    "--prefer-binary",
)

_REJECTED_DIRECTIVES = (
    "-e", "--editable",
)


def normalize_name(name: str) -> str:
    """PEP 503 normalization: lowercase, collapse -_. runs to -."""
    return re.sub(r"[-_.]+", "-", name).lower()


def sanitize_manifest(path: Path) -> list[PackagePin]:
    """
    Read a requirements manifest and return the requirements it
    contains. Pinned and unpinned lines are both accepted; the
    difference is recorded in `is_pinned`.

    Raises SanitizeError on the first line that can't be handled.
    """
    text = path.read_text(encoding="utf-8")
    pins: list[PackagePin] = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()

        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith(("\\", ";")):
            raise SanitizeError(
                "unsupported_continuation", line_number, raw_line
            )

        if line.startswith("-"):
            token = line.split()[0]
            if token in _REJECTED_DIRECTIVES:
                raise SanitizeError(
                    f"rejected_directive: {token}",
                    line_number, raw_line,
                )
            if token in _STRIPPED_DIRECTIVES:
                continue
            raise SanitizeError(
                f"unknown_directive: {token}", line_number, raw_line,
            )

        if " @ " in line:
            raise SanitizeError(
                "direct_url_not_allowed", line_number, raw_line,
            )

        if "\\" in line:
            raise SanitizeError(
                "multiline_hash_not_supported", line_number, raw_line,
            )

        match = _REQ_RE.match(line)
        if match is None:
            raise SanitizeError(
                "malformed_requirement", line_number, raw_line,
            )

        extras_group = match.group("extras")
        extras: tuple[str, ...] = ()
        if extras_group:
            inner = extras_group[1:-1]
            extras = tuple(
                e.strip() for e in inner.split(",") if e.strip()
            )

        marker = match.group("marker")
        if marker is not None:
            marker = marker.strip() or None

        op = match.group("op")
        version = match.group("version")
        variant = match.group("variant")

        if op is None or version is None:
            # No operator and no version: `pkg` alone.
            pins.append(PackagePin(
                name=normalize_name(match.group("name")),
                is_pinned=False,
                base_version="",
                local_variant="",
                raw_specifier="",
                extras=extras,
                environment_marker=marker,
                explicit_hashes=(),
                raw_line=raw_line,
                line_number=line_number,
            ))
            continue

        if op == "==":
            pins.append(PackagePin(
                name=normalize_name(match.group("name")),
                is_pinned=True,
                base_version=version,
                local_variant=variant or "",
                raw_specifier=f"=={version}" + (
                    f"+{variant}" if variant else ""
                ),
                extras=extras,
                environment_marker=marker,
                explicit_hashes=(),
                raw_line=raw_line,
                line_number=line_number,
            ))
            continue

        # Range or inequality. Version string is the constraint, not
        # a resolvable version. Keep the operator+version as the
        # raw specifier; pip resolves it later.
        spec = f"{op}{version}"
        pins.append(PackagePin(
            name=normalize_name(match.group("name")),
            is_pinned=False,
            base_version="",
            local_variant="",
            raw_specifier=spec,
            extras=extras,
            environment_marker=marker,
            explicit_hashes=(),
            raw_line=raw_line,
            line_number=line_number,
        ))

    if not pins:
        raise SanitizeError("empty_manifest", 0, "")

    return pins
