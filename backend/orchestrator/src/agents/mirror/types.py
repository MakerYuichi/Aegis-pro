"""
Dataclasses shared by the mirror's reader and resolver.

Three shapes:

  BuildRequirement    — a single requirement as declared by an sdist.
                        The name and specifier come from
                        `[build-system].requires`. May be bare
                        (`setuptools`), ranged (`cython<3`), or
                        pinned (`setuptools==60.0.0`).

  ResolvedRequirement — a requirement the resolver picked an exact
                        version for. Carries the version, the
                        wheel's sha256, and how the resolver chose
                        it (date-bounded or relaxed).

  ResolutionOutcome   — the result of resolving a whole list of
                        requirements. Success carries the resolved
                        list; failure carries a named reason and
                        the specific requirement that failed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class BuildRequirement:
    """
    One requirement, as declared by an sdist.

    name:             PEP 503 normalized package name.
    specifier:        as written: ">=40.8.0", "<3", "==60.0.0",
                      or "" for a bare name.
    source:           where the requirement came from. One of:
                        "pyproject"  — [build-system].requires
                        "default"    — pip's fallback when there's
                                       no pyproject.toml
                        "retry"      — discovered by round 2 of the
                                       bounded retry loop
    raw_line:         the original text, for error messages.
    """
    name: str
    specifier: str
    source: str
    raw_line: str


@dataclass(frozen=True)
class ResolvedRequirement:
    """
    A requirement the resolver pinned to an exact version.

    name:             PEP 503 normalized.
    version:          exact version, e.g. "68.2.2".
    filename:         the wheel filename that satisfies it.
    sha256:           the wheel's digest as PyPI publishes it, with
                      the "sha256:" prefix.
    upload_time:      ISO 8601 timestamp of the wheel on PyPI. Used
                      by the resolver to prove the date bound was
                      honored.
    source_index:     which index the wheel came from. "pypi" for
                      most, "pytorch_cpu" for torch-family.
    requested:        the BuildRequirement this satisfies.
    fallback_used:    True when the resolver relaxed the date bound
                      because nothing satisfied the original.
                      Recorded in the manifest so a reviewer can
                      see when the toolchain diverged from what
                      the sdist author would have built against.
    """
    name: str
    version: str
    filename: str
    sha256: str
    upload_time: str
    source_index: str
    requested: BuildRequirement
    fallback_used: bool = False


@dataclass(frozen=True)
class ResolutionOutcome:
    """
    The result of resolving a whole list of build requirements.

    success:         True when every requirement resolved.
    resolved:        the resolved list. Empty on failure.
    failed_name:     the name that failed. Empty on success.
    failed_reason:   a named reason for the failure. One of:
                       "no_matching_version"
                       "no_compatible_wheel"
                       "network_error"
                       "lookup_failed"
                     Empty on success.
    failed_detail:   a human-readable description. Empty on success.
    """
    success: bool
    resolved: list[ResolvedRequirement] = field(default_factory=list)
    failed_name: str = ""
    failed_reason: str = ""
    failed_detail: str = ""


@dataclass(frozen=True)
class SdistRef:
    url: str
    filename: str
    sha256: str
    upload_time: str
    name: str
    version: str
    size_bytes: int | None = None
