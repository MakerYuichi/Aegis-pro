"""
Tests for src.agents.mirror.resolver.

The resolver queries PyPI's JSON. Tests mock the fetch layer so
no network is required. A single integration test against PyPI is
skipped by default and enabled via a marker.

The core property: a version satisfying the specifier, with a
compatible wheel, published on or before the sdist's upload time,
is chosen over a newer version satisfying the same specifier.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.agents.mirror.resolver import BuildResolver, ResolverError
from src.agents.mirror.types import BuildRequirement


def _file(
    name: str,
    version: str,
    filename: str,
    upload: str,
    packagetype: str = "bdist_wheel",
    yanked: bool = False,
    sha: str = "abcd1234",
) -> dict:
    return {
        "filename": filename,
        "packagetype": packagetype,
        "upload_time_iso_8601": upload,
        "yanked": yanked,
        "digests": {"sha256": sha},
        "url": f"https://files.pythonhosted.org/packages/{filename}",
    }


def _pypi_payload(name: str, releases: dict) -> dict:
    return {"info": {"name": name}, "releases": releases}


class _FakeResponse:
    """Minimal stand-in for urlopen's context-manager response."""
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _req(name: str, specifier: str = "") -> BuildRequirement:
    return BuildRequirement(
        name=name,
        specifier=specifier,
        source="pyproject",
        raw_line=f"{name}{specifier}",
    )


def _resolver_with_payloads(payloads: dict[str, dict]) -> BuildResolver:
    resolver = BuildResolver(timeout_seconds=1, user_agent="test")

    def fake_fetch(name: str) -> dict:
        if name not in payloads:
            raise ResolverError("lookup_failed", f"{name} unknown")
        return payloads[name]

    resolver._fetch_json = fake_fetch  # type: ignore[method-assign]
    return resolver


# ── happy paths ─────────────────────────────────────────────────

def test_resolves_to_newest_before_date():
    payload = _pypi_payload("setuptools", {
        "40.8.0": [_file("setuptools", "40.8.0",
                          "setuptools-40.8.0-py2.py3-none-any.whl",
                          "2019-02-01T00:00:00Z")],
        "60.0.0": [_file("setuptools", "60.0.0",
                          "setuptools-60.0.0-py3-none-any.whl",
                          "2021-12-01T00:00:00Z")],
        "68.0.0": [_file("setuptools", "68.0.0",
                          "setuptools-68.0.0-py3-none-any.whl",
                          "2023-06-01T00:00:00Z")],
    })
    resolver = _resolver_with_payloads({"setuptools": payload})
    outcome = resolver.resolve_all(
        [_req("setuptools", ">=40.8.0")],
        as_of="2022-01-01T00:00:00Z",
        python_tag="cp311",
    )
    assert outcome.success
    assert outcome.resolved[0].version == "60.0.0"
    assert outcome.resolved[0].fallback_used is False
    assert outcome.resolved[0].sha256 == "sha256:abcd1234"


def test_resolves_pinned_exact():
    payload = _pypi_payload("wheel", {
        "0.38.0": [_file("wheel", "0.38.0",
                          "wheel-0.38.0-py3-none-any.whl",
                          "2022-10-01T00:00:00Z")],
        "0.40.0": [_file("wheel", "0.40.0",
                          "wheel-0.40.0-py3-none-any.whl",
                          "2023-10-01T00:00:00Z")],
    })
    resolver = _resolver_with_payloads({"wheel": payload})
    outcome = resolver.resolve_all(
        [_req("wheel", "==0.38.0")],
        as_of="2024-01-01T00:00:00Z",
        python_tag="cp311",
    )
    assert outcome.success
    assert outcome.resolved[0].version == "0.38.0"


def test_range_less_than_excludes_newer():
    payload = _pypi_payload("cython", {
        "0.29.36": [_file("cython", "0.29.36",
                          "Cython-0.29.36-py2.py3-none-any.whl",
                          "2023-01-01T00:00:00Z")],
        "3.0.0": [_file("cython", "3.0.0",
                          "Cython-3.0.0-py3-none-any.whl",
                          "2023-07-01T00:00:00Z")],
    })
    resolver = _resolver_with_payloads({"cython": payload})
    outcome = resolver.resolve_all(
        [_req("cython", "<3")],
        as_of="2024-01-01T00:00:00Z",
        python_tag="cp311",
    )
    assert outcome.success
    assert outcome.resolved[0].version == "0.29.36"


def test_wheel_published_after_date_is_skipped():
    """A version whose only wheel is published AFTER the sdist date
    doesn't satisfy the requirement under the date bound."""
    payload = _pypi_payload("setuptools", {
        "50.0.0": [_file("setuptools", "50.0.0",
                          "setuptools-50.0.0-py3-none-any.whl",
                          "2020-08-01T00:00:00Z")],
        "55.0.0": [_file("setuptools", "55.0.0",
                          "setuptools-55.0.0-py3-none-any.whl",
                          "2021-09-01T00:00:00Z")],
    })
    resolver = _resolver_with_payloads({"setuptools": payload})
    outcome = resolver.resolve_all(
        [_req("setuptools")],
        as_of="2021-01-01T00:00:00Z",  # between 50 and 55
        python_tag="cp311",
    )
    assert outcome.success
    assert outcome.resolved[0].version == "50.0.0"


# ── relaxation (fallback) ───────────────────────────────────────

def test_relaxes_date_bound_and_records_fallback():
    """Nothing satisfies the date. The resolver relaxes and records
    fallback_used=True so a reviewer can see when the toolchain
    diverged from what the sdist author would have had."""
    payload = _pypi_payload("setuptools", {
        "80.0.0": [_file("setuptools", "80.0.0",
                          "setuptools-80.0.0-py3-none-any.whl",
                          "2025-01-01T00:00:00Z")],
    })
    resolver = _resolver_with_payloads({"setuptools": payload})
    outcome = resolver.resolve_all(
        [_req("setuptools")],
        as_of="2020-01-01T00:00:00Z",  # everything is after this
        python_tag="cp311",
    )
    assert outcome.success
    assert outcome.resolved[0].version == "80.0.0"
    assert outcome.resolved[0].fallback_used is True


# ── wheel-tag filtering ─────────────────────────────────────────

def test_skips_versions_without_compatible_wheel():
    payload = _pypi_payload("setuptools", {
        "40.8.0": [_file("setuptools", "40.8.0",
                          "setuptools-40.8.0-py2.py3-none-any.whl",
                          "2019-02-01T00:00:00Z")],
        "70.0.0": [_file("setuptools", "70.0.0",
                          "setuptools-70.0.0.tar.gz",
                          "2024-01-01T00:00:00Z",
                          packagetype="sdist")],
    })
    resolver = _resolver_with_payloads({"setuptools": payload})
    outcome = resolver.resolve_all(
        [_req("setuptools")],
        as_of="2025-01-01T00:00:00Z",
        python_tag="cp311",
    )
    assert outcome.success
    # 70.0.0 exists but has no wheel — skipped.
    assert outcome.resolved[0].version == "40.8.0"


def test_all_versions_no_wheel_returns_failure():
    payload = _pypi_payload("somepkg", {
        "1.0": [_file("somepkg", "1.0", "somepkg-1.0.tar.gz",
                      "2023-01-01T00:00:00Z",
                      packagetype="sdist")],
    })
    resolver = _resolver_with_payloads({"somepkg": payload})
    outcome = resolver.resolve_all(
        [_req("somepkg")],
        as_of="2024-01-01T00:00:00Z",
        python_tag="cp311",
    )
    assert not outcome.success
    assert outcome.failed_reason == "no_compatible_wheel"


def test_yanked_version_skipped():
    payload = _pypi_payload("setuptools", {
        "60.0.0": [_file("setuptools", "60.0.0",
                          "setuptools-60.0.0-py3-none-any.whl",
                          "2021-12-01T00:00:00Z")],
        "61.0.0": [_file("setuptools", "61.0.0",
                          "setuptools-61.0.0-py3-none-any.whl",
                          "2022-03-01T00:00:00Z",
                          yanked=True)],
    })
    resolver = _resolver_with_payloads({"setuptools": payload})
    outcome = resolver.resolve_all(
        [_req("setuptools")],
        as_of="2025-01-01T00:00:00Z",
        python_tag="cp311",
    )
    assert outcome.success
    assert outcome.resolved[0].version == "60.0.0"


# ── failure modes ───────────────────────────────────────────────

def test_unknown_package_returns_lookup_failed():
    resolver = _resolver_with_payloads({})
    outcome = resolver.resolve_all(
        [_req("does-not-exist")],
        as_of="2024-01-01T00:00:00Z",
        python_tag="cp311",
    )
    assert not outcome.success
    assert outcome.failed_reason == "lookup_failed"
    assert outcome.failed_name == "does-not-exist"


def test_no_satisfying_version_returns_no_matching_version():
    payload = _pypi_payload("cython", {
        "3.0.0": [_file("cython", "3.0.0",
                          "Cython-3.0.0-py3-none-any.whl",
                          "2023-07-01T00:00:00Z")],
    })
    resolver = _resolver_with_payloads({"cython": payload})
    outcome = resolver.resolve_all(
        [_req("cython", "<3")],
        as_of="2024-01-01T00:00:00Z",
        python_tag="cp311",
    )
    assert not outcome.success
    assert outcome.failed_reason == "no_matching_version"


# ── multiple requirements ───────────────────────────────────────

def test_one_failure_fails_the_whole_outcome():
    payloads = {
        "setuptools": _pypi_payload("setuptools", {
            "60.0.0": [_file("setuptools", "60.0.0",
                              "setuptools-60.0.0-py3-none-any.whl",
                              "2022-01-01T00:00:00Z")],
        }),
    }
    resolver = _resolver_with_payloads(payloads)
    outcome = resolver.resolve_all(
        [_req("setuptools"), _req("does-not-exist")],
        as_of="2024-01-01T00:00:00Z",
        python_tag="cp311",
    )
    assert not outcome.success
    assert outcome.failed_name == "does-not-exist"


def test_multiple_successes_all_resolve():
    payloads = {
        "setuptools": _pypi_payload("setuptools", {
            "60.0.0": [_file("setuptools", "60.0.0",
                              "setuptools-60.0.0-py3-none-any.whl",
                              "2022-01-01T00:00:00Z")],
        }),
        "wheel": _pypi_payload("wheel", {
            "0.38.0": [_file("wheel", "0.38.0",
                              "wheel-0.38.0-py3-none-any.whl",
                              "2022-11-01T00:00:00Z")],
        }),
    }
    resolver = _resolver_with_payloads(payloads)
    outcome = resolver.resolve_all(
        [_req("setuptools", ">=40"), _req("wheel")],
        as_of="2024-01-01T00:00:00Z",
        python_tag="cp311",
    )
    assert outcome.success
    assert len(outcome.resolved) == 2
    assert {r.name for r in outcome.resolved} == {"setuptools", "wheel"}


# ── JSON cache ─────────────────────────────────────────────────

def test_json_is_cached_per_package():
    """The resolver caches PyPI JSON per package. Repeated
    resolutions of the same package hit the network once."""
    calls = []

    def fake_urlopen(req, timeout):
        # req is a urllib.request.Request; pull the URL and record
        # the package name from the path.
        url = req.full_url
        # https://pypi.org/pypi/{name}/json
        name = url.split("/pypi/")[1].split("/")[0]
        calls.append(name)
        payload = _pypi_payload(name, {
            "1.0": [_file(
                name, "1.0",
                f"{name}-1.0-py3-none-any.whl",
                "2023-01-01T00:00:00Z",
            )],
        })
        # Mimic urlopen's context-manager behaviour.
        resp = _FakeResponse(json.dumps(payload).encode())
        return resp

    resolver = BuildResolver(timeout_seconds=1, user_agent="test")

    with patch(
        "src.agents.mirror.resolver.urllib.request.urlopen",
        side_effect=fake_urlopen,
    ):
        resolver.resolve_all(
            [_req("a"), _req("a"), _req("b")],
            as_of="2024-01-01T00:00:00Z",
            python_tag="cp311",
        )

    assert calls == ["a", "b"]


# ── torch source index routing ─────────────────────────────────

def test_torch_routes_to_cpu_index():
    payload = _pypi_payload("torch", {
        "2.6.0": [_file("torch", "2.6.0",
                         "torch-2.6.0-cp311-cp311-linux_x86_64.whl",
                         "2024-01-01T00:00:00Z")],
    })
    resolver = _resolver_with_payloads({"torch": payload})
    outcome = resolver.resolve_all(
        [_req("torch", ">=2.6.0")],
        as_of="2025-01-01T00:00:00Z",
        python_tag="cp311",
    )
    assert outcome.success
    assert (
        outcome.resolved[0].source_index
        == "https://download.pytorch.org/whl/cpu"
    )
