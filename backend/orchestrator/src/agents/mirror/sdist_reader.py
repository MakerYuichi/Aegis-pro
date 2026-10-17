"""
Read [build-system].requires from an sdist tarball, in memory.

Bounded and defensive:
  - The tarball is read into a BytesIO, never extracted to disk.
  - Individual members are read up to a size limit.
  - Only one member is read: pyproject.toml at the sdist's root.
  - The reader tolerates the common malformation of a pyproject
    that can't be parsed, returning [] rather than raising — the
    resolver then falls back to pip's default, same as if there
    were no pyproject.toml at all.

Design note: the reader never calls any code from the sdist. It
reads bytes. Parsing TOML is a pure data operation. Nothing in the
extracted content executes in this process.

Why not extract the whole tarball: an sdist is untrusted input
from a repo we don't control. Tar bombs, path traversal, symlinks
pointing outside — every one of those is a real attack on a
process that extracts. Reading one member by name and parsing it
as data eliminates the class entirely.
"""
from __future__ import annotations

import io
import tarfile
import tomllib
from typing import Optional

from loguru import logger

from src.agents.mirror.types import BuildRequirement
from src.agents.prefetch.sanitize import normalize_name


# Cap on any single member read from the tarball. pyproject.toml
# is essentially always under 10 KB; 64 KB is generous.
MAX_MEMBER_BYTES = 64 * 1024

# Cap on the number of members we're willing to iterate while
# searching for pyproject.toml. A hostile tarball could contain
# a million empty members to burn CPU during the scan.
MAX_MEMBERS_TO_SCAN = 10_000


class SdistReaderError(Exception):
    """Raised when the tarball itself can't be read — not when the
    pyproject is malformed. A malformed pyproject returns []."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def read_build_system_requires(
    tarball_bytes: bytes,
) -> list[BuildRequirement]:
    """
    Return the [build-system].requires declared by an sdist.

    Returns an empty list when:
      - the sdist has no pyproject.toml
      - the pyproject.toml has no [build-system] table
      - the pyproject.toml can't be parsed
      - the [build-system].requires key is missing

    In all of those cases the caller falls back to pip's default
    (`setuptools>=40.8.0`). That matches how pip itself handles a
    legacy setup.py-only sdist.

    Raises SdistReaderError only when the tarball isn't a valid tar
    or is malformed beyond reading. A reader error is an
    infrastructure failure; the caller reports
    `sdist_malformed` rather than the pip-default fallback.
    """
    try:
        tf = tarfile.open(fileobj=io.BytesIO(tarball_bytes), mode="r:*")
    except tarfile.TarError as e:
        raise SdistReaderError(
            "not_a_tarball", f"{type(e).__name__}: {e}"
        ) from e

    with tf:
        pyproject_member: Optional[tarfile.TarInfo] = None
        scanned = 0
        for member in tf:
            scanned += 1
            if scanned > MAX_MEMBERS_TO_SCAN:
                raise SdistReaderError(
                    "too_many_members",
                    f"scanned {MAX_MEMBERS_TO_SCAN}, "
                    f"still no pyproject.toml",
                )
            # Only accept a regular file at depth 2 whose name ends
            # in /pyproject.toml. Sdists place pyproject at
            # `<root>/pyproject.toml` where `<root>` is
            # `<name>-<version>`.
            if not member.isfile():
                continue
            parts = member.name.split("/")
            if len(parts) != 2:
                continue
            if parts[1] != "pyproject.toml":
                continue
            pyproject_member = member
            break

        if pyproject_member is None:
            logger.debug(
                "sdist_reader: no pyproject.toml found, "
                "caller will fall back to pip default"
            )
            return []

        if pyproject_member.size > MAX_MEMBER_BYTES:
            raise SdistReaderError(
                "pyproject_too_large",
                f"{pyproject_member.size} bytes "
                f"> {MAX_MEMBER_BYTES}",
            )

        raw = tf.extractfile(pyproject_member)
        if raw is None:
            raise SdistReaderError(
                "pyproject_unreadable", pyproject_member.name,
            )
        text_bytes = raw.read(MAX_MEMBER_BYTES)

    try:
        data = tomllib.loads(text_bytes.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        logger.warning(
            f"sdist_reader: malformed pyproject.toml ({e}); "
            f"caller will fall back to pip default"
        )
        return []

    build_system = data.get("build-system")
    if not isinstance(build_system, dict):
        return []

    requires = build_system.get("requires")
    if not isinstance(requires, list):
        return []

    parsed: list[BuildRequirement] = []
    for raw_req in requires:
        if not isinstance(raw_req, str):
            continue
        req = _parse_requirement(raw_req, source="pyproject")
        if req is not None:
            parsed.append(req)
    return parsed


# A permissive split of `name[extras]specifier`. Extras are dropped
# here — build requirements rarely carry them, and pip treats them
# as part of the name for resolution. The resolver adds extras back
# when the requirement string contains them.
_REQ_RE = None  # lazy import to avoid a module-level import cycle


def _parse_requirement(
    raw: str, source: str,
) -> Optional[BuildRequirement]:
    """
    Parse `name[extras]op version` into a BuildRequirement.

    Accepts the same shapes the manifest sanitizer accepts:
      name
      name op version
      name[extras] op version
    Environment markers are dropped — build-system.requires almost
    never uses them, and the resolver's job is to pick a version,
    not to condition on the environment.

    Returns None when the requirement is unparseable. That's a
    warning, not an error: a bad requirement string in a
    pyproject.toml gets skipped, and the resolver proceeds with the
    ones it understands.
    """
    import re
    global _REQ_RE
    if _REQ_RE is None:
        _REQ_RE = re.compile(
            r"^\s*"
            r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
            r"(?:\[[^\]]+\])?"
            r"\s*"
            r"(?:(?P<op>==|>=|<=|~=|!=|>|<)\s*"
            r"(?P<version>[A-Za-z0-9][A-Za-z0-9._-]*))?"
            r"\s*"
            r"(?:;.*)?$"
        )

    m = _REQ_RE.match(raw)
    if m is None:
        logger.warning(
            f"sdist_reader: unparseable build requirement {raw!r}"
        )
        return None

    op = m.group("op") or ""
    version = m.group("version") or ""
    specifier = f"{op}{version}" if op else ""

    return BuildRequirement(
        name=normalize_name(m.group("name")),
        specifier=specifier,
        source=source,
        raw_line=raw,
    )
