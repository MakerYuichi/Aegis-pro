"""
Route a PackagePin to the index it should be fetched from.

Policy is ours, not the manifest's. The manifest said `--extra-index-url
https://download.pytorch.org/whl/cpu`; we strip that and route torch
there ourselves because we know torch's CPU wheel lives there. If a
repo points `--index-url` at a mirror we don't trust, the manifest's
directive is discarded and our default applies.

The routing is keyed on (name, local_variant). A pin for
`torch==2.14.0+cpu` routes to download.pytorch.org. A pin for
`torch==2.14.0` — no variant — routes to PyPI, which serves the GPU
wheel by default. That's the 2GB problem. Rather than override the
manifest, we warn: the user almost certainly meant CPU, and the
warning names the fix. Overriding the manifest silently would be the
kind of thing that's right 90% of the time and catastrophic the
other 10%.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.agents.prefetch.sanitize import PackagePin


DEFAULT_INDEX_URL = "https://pypi.org/simple/"


# The variant-aware override map. Presence of `(name, variant)`
# means: this exact combination resolves from this index.
#
# Adding entries here is a deliberate act. Every entry widens the
# set of hosts the prefetcher will contact. Review each addition.
VARIANT_INDEX_OVERRIDES: dict[tuple[str, str], str] = {
    ("torch", "cpu"):       "https://download.pytorch.org/whl/cpu",
    ("torchvision", "cpu"): "https://download.pytorch.org/whl/cpu",
    ("torchaudio", "cpu"):  "https://download.pytorch.org/whl/cpu",
}


# The bare-name override map. Presence of `name` (no variant) means:
# pins without a variant resolve here. Empty by default.
BASE_INDEX_OVERRIDES: dict[str, str] = {}


# Hosts the prefetcher's network is permitted to reach. Enforced by
# the Docker network's scoped resolver (see docker-compose.yml) and
# also asserted here so a bad policy edit fails at test time.
ALLOWED_HOSTS: frozenset[str] = frozenset({
    "pypi.org",
    "files.pythonhosted.org",
    "download.pytorch.org",
})


class PolicyError(Exception):
    """Raised when a pin can't be routed under current policy."""

    def __init__(self, reason: str, pin: PackagePin):
        self.reason = reason
        self.pin = pin
        super().__init__(f"{reason}: {pin.raw_line!r}")


@dataclass(frozen=True)
class IndexRoute:
    """
    Where a pin resolves from, and why.

    reason is one of:
        "default"                    → DEFAULT_INDEX_URL
        "known_variant_override"     → VARIANT_INDEX_OVERRIDES hit
        "base_name_override"         → BASE_INDEX_OVERRIDES hit
        "default_variant_mismatch"   → no variant on the pin, but a
                                       variant override exists for
                                       this name. Warning condition;
                                       routes to default anyway.
    """
    index_url: str
    reason: str


def route_pin(pin: PackagePin) -> IndexRoute:
    """
    Return the IndexRoute for this pin.

    Raises PolicyError when the pin names a local variant we don't
    have an override for. Guessing would be worse than failing:
    a `torch==2.14.0+rocm` pin routed to PyPI would fetch a wheel
    that doesn't exist, and routed to a random mirror could fetch
    a build we haven't vetted.
    """
    if pin.local_variant:
        key = (pin.name, pin.local_variant)
        if key in VARIANT_INDEX_OVERRIDES:
            return IndexRoute(
                index_url=VARIANT_INDEX_OVERRIDES[key],
                reason="known_variant_override",
            )
        raise PolicyError(
            f"unknown_local_variant: {pin.name}+{pin.local_variant}",
            pin,
        )

    if pin.name in BASE_INDEX_OVERRIDES:
        return IndexRoute(
            index_url=BASE_INDEX_OVERRIDES[pin.name],
            reason="base_name_override",
        )

    # Warn if a variant-only override exists for this name and the
    # pin didn't specify it. This is the torch-no-variant case.
    for (name, _variant) in VARIANT_INDEX_OVERRIDES:
        if name == pin.name:
            return IndexRoute(
                index_url=DEFAULT_INDEX_URL,
                reason="default_variant_mismatch",
            )

    return IndexRoute(index_url=DEFAULT_INDEX_URL, reason="default")
