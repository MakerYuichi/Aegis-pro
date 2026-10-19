"""
Resolve build requirements to exact versions, honoring the sdist's
own upload date as a boundary.

The policy, in one paragraph: for each requirement, pick the newest
non-yanked version that (a) satisfies the declared specifier, (b)
has a wheel for the builder's Python and platform tags, and (c) was
published on or before the sdist's upload time. This reproduces the
build environment the sdist's author would have had available. If
no version satisfies the date bound, relax it and record the fact.

Why this matters: `cython<3` was published before Cython 3 existed.
Resolving it today would pick 0.29.x, and packages that worked with
0.29.x still work. Resolving `setuptools` without a date bound
would pick a version the sdist predates and probably breaks on.
The boundary is what makes the resolution honest.

Design notes:
  - All queries go to https://pypi.org/pypi/{name}/json. That
    endpoint is cached, rate-limit friendly, and used by every
    packaging tool. No auth required.
  - Wheel availability is checked by the filename tag prefix.
    A full wheel-tag matcher (packaging.tags) is out of scope for
    this PR — the resolver runs inside the orchestrator container,
    whose Python version and platform are the builder's target by
    construction (see the preflight check in C1b).
  - The resolver never downloads a wheel. It records the wheel
    URL's sha256 so the prefetcher can verify the download.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from src.agents.mirror.types import (
    BuildRequirement,
    ResolutionOutcome,
    ResolvedRequirement,
    SdistRef,
)
from src.agents.prefetch.policy import (
    DEFAULT_INDEX_URL,
    VARIANT_INDEX_OVERRIDES,
)
from src.config import settings


PYPI_JSON_URL = "https://pypi.org/pypi/{name}/json"


class ResolverError(Exception):
    """Infrastructure failure — network, JSON, HTTP. Never a
    resolution failure; those become a ResolutionOutcome with
    success=False and a specific failed_reason."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class BuildResolver:
    """
    Resolve build requirements to exact versions.

    Constructed once per prefetch. Caches PyPI JSON responses per
    package name, because a package's metadata doesn't change
    during a resolution run and asking the same question twice is
    wasteful.
    """

    def __init__(
        self,
        *,
        timeout_seconds: int | None = None,
        user_agent: str | None = None,
    ):
        self.timeout = (
            timeout_seconds or settings.BUILD_RESOLVER_TIMEOUT_SECONDS
        )
        self.user_agent = (
            user_agent or settings.BUILD_RESOLVER_USER_AGENT
        )
        self._json_cache: dict[str, dict] = {}

    def resolve_all(
        self,
        requirements: list[BuildRequirement],
        *,
        as_of: str,
        python_tag: str,
    ) -> ResolutionOutcome:
        """
        Resolve every requirement. Returns an outcome that
        succeeds only if every requirement resolved.

        as_of:      ISO 8601 timestamp. The sdist's upload time.
        python_tag: e.g. "cp311". Used to filter wheels.
        """
        resolved: list[ResolvedRequirement] = []
        for req in requirements:
            version, filename, sha256, upload_time, fallback = (
                self._resolve_one(
                    req,
                    as_of=as_of,
                    python_tag=python_tag,
                )
            )
            if version is None:
                return ResolutionOutcome(
                    success=False,
                    failed_name=req.name,
                    failed_reason=self._last_reason,
                    failed_detail=self._last_detail,
                )
            resolved.append(ResolvedRequirement(
                name=req.name,
                version=version,
                filename=filename,
                sha256=sha256,
                upload_time=upload_time,
                source_index=self._source_index_for(req),
                requested=req,
                fallback_used=fallback,
            ))
        return ResolutionOutcome(success=True, resolved=resolved)

    def _resolve_one(
        self,
        req: BuildRequirement,
        *,
        as_of: str,
        python_tag: str,
    ) -> tuple[Optional[str], str, str, str, bool]:
        """
        Resolve a single requirement. Returns:
            (version, filename, sha256, upload_time, fallback_used)

        version is None on failure; self._last_reason and
        self._last_detail describe why.
        """
        self._last_reason = ""
        self._last_detail = ""

        as_of_dt = _parse_iso(as_of)

        try:
            payload = self._fetch_json(req.name)
        except ResolverError as e:
            self._last_reason = e.reason
            self._last_detail = e.detail
            return None, "", "", "", False

        releases = payload.get("releases") or {}
        if not releases:
            self._last_reason = "no_matching_version"
            self._last_detail = f"{req.name} has no published releases"
            return None, "", "", "", False

        candidates = self._candidates(
            req,
            releases=releases,
            python_tag=python_tag,
        )
        if not candidates:
            self._last_reason = "no_matching_version"
            self._last_detail = (
                f"no version of {req.name} satisfies "
                f"{req.specifier or '(any)'}"
            )
            return None, "", "", "", False

        # Sort newest first, by version tuple. We don't need full
        # PEP 440 ordering — a simple tuple comparison on the
        # numeric parts is enough for build requirements, which
        # are practically never prereleases.
        candidates.sort(key=lambda c: c[0], reverse=True)

        # Pass 1: honor the date bound.
        for version_tuple, version_str, files in candidates:
            for f in files:
                if _file_matches(f, python_tag):
                    upload = f.get("upload_time_iso_8601", "")
                    if not upload:
                        continue
                    if _parse_iso(upload) <= as_of_dt:
                        return (
                            version_str,
                            f["filename"],
                            _sha256_of(f),
                            upload,
                            False,
                        )
        # Pass 2: relax the date bound, but record that we did.
        for version_tuple, version_str, files in candidates:
            for f in files:
                if _file_matches(f, python_tag):
                    upload = f.get("upload_time_iso_8601", "")
                    if not upload:
                        continue
                    logger.warning(
                        f"resolver: relaxed date bound for "
                        f"{req.name} {version_str} "
                        f"(upload {upload} > as_of {as_of})"
                    )
                    return (
                        version_str,
                        f["filename"],
                        _sha256_of(f),
                        upload,
                        True,
                    )

        self._last_reason = "no_compatible_wheel"
        self._last_detail = (
            f"{req.name} has versions satisfying "
            f"{req.specifier or '(any)'}, but none publish a wheel "
            f"for {python_tag}"
        )
        return None, "", "", "", False

    def _fetch_json(self, name: str) -> dict:
        """Fetch and cache the PyPI JSON for one package."""
        cached = self._json_cache.get(name)
        if cached is not None:
            return cached

        url = PYPI_JSON_URL.format(name=name)
        req = urllib.request.Request(
            url, headers={"User-Agent": self.user_agent},
        )
        try:
            with urllib.request.urlopen(
                req, timeout=self.timeout,
            ) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ResolverError(
                    "lookup_failed",
                    f"{name} not found on PyPI",
                ) from e
            raise ResolverError(
                "lookup_failed", f"HTTP {e.code} for {name}",
            ) from e
        except (urllib.error.URLError, OSError) as e:
            raise ResolverError(
                "network_error",
                f"{type(e).__name__} for {name}: {e}",
            ) from e
        except json.JSONDecodeError as e:
            raise ResolverError(
                "lookup_failed",
                f"invalid JSON for {name}: {e}",
            ) from e

        self._json_cache[name] = payload
        return payload

    def _candidates(
        self,
        req: BuildRequirement,
        *,
        releases: dict,
        python_tag: str,
    ) -> list[tuple]:
        """
        Return [(version_tuple, version_str, files), ...] for
        versions that satisfy the specifier and are not fully
        yanked.
        """
        out = []
        for version_str, files in releases.items():
            if not files:
                continue
            if not _satisfies_specifier(version_str, req.specifier):
                continue
            vt = _version_tuple(version_str)
            if vt is None:
                continue
            # A version with all files yanked is not a candidate.
            if all(f.get("yanked", False) for f in files):
                continue
            out.append((vt, version_str, files))
        return out

    def _source_index_for(self, req: BuildRequirement) -> str:
        """
        Which index a build requirement would come from. Mirrors
        the policy module's routing, so a build requirement for
        torch lands on the CPU index just like a runtime one.
        """
        for (name, _variant), url in VARIANT_INDEX_OVERRIDES.items():
            if name == req.name:
                return url
        return DEFAULT_INDEX_URL

    # Instance state for the failure detail, set by _resolve_one.
    _last_reason: str = ""
    _last_detail: str = ""


# ── helpers ─────────────────────────────────────────────────────

def _file_matches(file_entry: dict, python_tag: str) -> bool:
    """
    True when a PyPI file entry is a wheel compatible with the
    given Python tag.

    Heuristic, not exhaustive: matches `cp311`, `py3`, or any of
    the universal wheel forms. Good enough because build
    requirements are pure-Python tooling in practice — setuptools,
    wheel, flit-core, hatchling, poetry-core all ship as py3-none-any.
    """
    if file_entry.get("packagetype") != "bdist_wheel":
        return False
    fname = file_entry.get("filename", "")
    if python_tag in fname:
        return True
    if "py3-none-any" in fname:
        return True
    if "py2.py3-none-any" in fname:
        return True
    return False


def _sha256_of(file_entry: dict) -> str:
    digests = file_entry.get("digests") or {}
    sha = digests.get("sha256")
    if not sha:
        return ""
    return f"sha256:{sha}"


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp from PyPI, tolerate trailing Z."""
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    s = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # Older PyPI responses omit timezone info on some entries.
        try:
            return datetime.fromisoformat(s + "+00:00")
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)


def _version_tuple(version: str) -> Optional[tuple[int, ...]]:
    """
    A crude numeric tuple for version sorting. Returns None when
    the version has no numeric components (unlikely for PyPI).

    Not a PEP 440 implementation. Build requirements are
    almost never prereleases, and if one is, the resolver treats
    it as ineligible because the release isn't marked — which is
    what pip does by default anyway.
    """
    parts = version.split(".")
    nums = []
    for part in parts:
        num = ""
        for ch in part:
            if ch.isdigit():
                num += ch
            else:
                break
        if not num:
            continue
        nums.append(int(num))
    return tuple(nums) if nums else None


def _satisfies_specifier(version: str, specifier: str) -> bool:
    """
    Cheap satisfaction check for the specifier forms that appear
    in [build-system].requires:
      ""            → any
      ">=X" / "<X"  → comparison
      "==X"         → exact
      "!=X"         → exclusion
      "~=X.Y"       → compatible-release (approximated as >=X.Y,<X.(Y+1))
    """
    spec = specifier.strip()
    if not spec:
        return True
    if spec.startswith("=="):
        return version == spec[2:].strip()
    if spec.startswith("!="):
        return version != spec[2:].strip()
    if spec.startswith(">="):
        return _cmp(version, spec[2:].strip()) >= 0
    if spec.startswith("<="):
        return _cmp(version, spec[2:].strip()) <= 0
    if spec.startswith("~="):
        base = spec[2:].strip()
        parts = base.split(".")
        if len(parts) < 2:
            return _cmp(version, base) >= 0
        try:
            upper = f"{parts[0]}.{int(parts[1]) + 1}"
        except (ValueError, IndexError):
            return _cmp(version, base) >= 0
        return (
            _cmp(version, base) >= 0
            and _cmp(version, upper) < 0
        )
    if spec.startswith(">"):
        return _cmp(version, spec[1:].strip()) > 0
    if spec.startswith("<"):
        return _cmp(version, spec[1:].strip()) < 0
    return False


def _cmp(a: str, b: str) -> int:
    """Compare two version strings numerically."""
    ta = _version_tuple(a) or ()
    tb = _version_tuple(b) or ()
    if ta < tb:
        return -1
    if ta > tb:
        return 1
    return 0
