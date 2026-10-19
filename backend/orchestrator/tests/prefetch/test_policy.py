"""
Tests for src.agents.prefetch.policy.

Routing rules:
    * a pin with a local variant and a matching override routes to it
    * a pin with a local variant and no matching override raises
    * a pin without a local variant routes by base-name override if
      one exists, else to PyPI
    * a pin without a variant whose name has a variant-only override
      routes to PyPI but signals default_variant_mismatch so the
      caller can warn
"""
from __future__ import annotations

import pytest

from src.agents.prefetch.policy import (
    DEFAULT_INDEX_URL,
    IndexRoute,
    PolicyError,
    route_pin,
)
from src.agents.prefetch.sanitize import PackagePin


def _pin(
    name: str,
    base_version: str = "1.0",
    variant: str = "",
    extras: tuple[str, ...] = (),
) -> PackagePin:
    """
    Construct a pinned PackagePin. Tests that need an unpinned pin
    use _unpinned_pin below. The two shapes differ enough that
    keeping them separate makes each test's intent clearer.
    """
    specifier = f"=={base_version}"
    if variant:
        specifier += f"+{variant}"
    return PackagePin(
        name=name,
        is_pinned=True,
        base_version=base_version,
        local_variant=variant,
        raw_specifier=specifier,
        extras=extras,
        environment_marker=None,
        explicit_hashes=(),
        raw_line=f"{name}{specifier}",
        line_number=1,
    )


def _unpinned_pin(
    name: str,
    raw_specifier: str = "",
    extras: tuple[str, ...] = (),
) -> PackagePin:
    return PackagePin(
        name=name,
        is_pinned=False,
        base_version="",
        local_variant="",
        raw_specifier=raw_specifier,
        extras=extras,
        environment_marker=None,
        explicit_hashes=(),
        raw_line=f"{name}{raw_specifier}",
        line_number=1,
    )


# ── default routing ─────────────────────────────────────────────

def test_plain_package_routes_to_pypi():
    route = route_pin(_pin("fastapi", "0.115.11"))
    assert route.index_url == DEFAULT_INDEX_URL
    assert route.reason == "default"


def test_unpinned_package_routes_to_pypi():
    route = route_pin(_unpinned_pin("httpx", ">=0.28.1"))
    assert route.index_url == DEFAULT_INDEX_URL
    assert route.reason == "default"


# ── variant routing (Option C) ─────────────────────────────────

def test_torch_cpu_routes_to_pytorch_index():
    route = route_pin(_pin("torch", "2.14.0", variant="cpu"))
    assert route.index_url == "https://download.pytorch.org/whl/cpu"
    assert route.reason == "known_variant_override"


def test_torchvision_cpu_routes_to_pytorch_index():
    route = route_pin(_pin("torchvision", "0.29.0", variant="cpu"))
    assert route.index_url == "https://download.pytorch.org/whl/cpu"


def test_unknown_variant_rejected():
    with pytest.raises(PolicyError) as exc_info:
        route_pin(_pin("torch", "2.14.0", variant="rocm"))
    assert "unknown_local_variant" in str(exc_info.value)


def test_unknown_variant_rejected_for_arbitrary_package():
    with pytest.raises(PolicyError):
        route_pin(_pin("fastapi", "0.115.11", variant="custom"))


# ── the variant-mismatch warning ────────────────────────────────

def test_torch_without_variant_warns_and_routes_to_pypi():
    """
    The case that produces the 2GB GPU wheel. The policy doesn't
    override the manifest; it routes to default and flags the
    mismatch so the caller can log a warning naming the fix.
    """
    route = route_pin(_pin("torch", "2.14.0"))
    assert route.index_url == DEFAULT_INDEX_URL
    assert route.reason == "default_variant_mismatch"


def test_torch_unpinned_also_warns():
    """
    An unpinned torch range also routes to the default index and
    signals the mismatch. The policy can't assume the range's
    resolved version will be CPU-only.
    """
    route = route_pin(_unpinned_pin("torch", ">=2.6.0"))
    assert route.index_url == DEFAULT_INDEX_URL
    assert route.reason == "default_variant_mismatch"


def test_numpy_without_variant_is_plain_default():
    """No variant override exists for numpy, so no mismatch flag."""
    route = route_pin(_pin("numpy", "1.24.3"))
    assert route.reason == "default"


# ── every override is a valid index host ────────────────────────

def test_all_variant_overrides_are_allowlisted():
    """A policy edit that adds an index outside ALLOWED_HOSTS
    should fail CI. This test is the enforcement."""
    from urllib.parse import urlparse
    from src.agents.prefetch.policy import (
        ALLOWED_HOSTS,
        VARIANT_INDEX_OVERRIDES,
    )
    for (name, variant), url in VARIANT_INDEX_OVERRIDES.items():
        host = urlparse(url).hostname
        assert host in ALLOWED_HOSTS, (
            f"override {name}+{variant} points at {host!r}, "
            f"which is not in ALLOWED_HOSTS"
        )
