"""
Mirror: the sdist → wheel build cache for source-only Python packages.

This package implements the "build once, cache forever" pattern for
packages that PyPI publishes as source distributions only. The
sub-packages and modules:

  sdist_reader       — read a build-system.requires declaration from
                       an sdist tarball, in memory, bounded.
  resolver           — resolve a build requirement to an exact pin,
                       honoring the sdist's own upload date.
  types              — dataclasses shared across the modules.

Not in this package (yet):
  fetch              — download wheels into the cache (later)
  build              — build an sdist in a sandboxed container (later)
  smoke              — structural + import validation of built wheels
  writer             — atomic publish to the mirror directory

Splitting the package along these lines lets the resolver be tested
in isolation (pure Python, no Docker) before the build pipeline is
layered on top.
"""
from src.agents.mirror.types import (
    BuildRequirement,
    ResolutionOutcome,
    ResolvedRequirement,
)
from src.agents.mirror.sdist_reader import (
    SdistReaderError,
    read_build_system_requires,
)
from src.agents.mirror.resolver import (
    BuildResolver,
    ResolverError,
)

__all__ = [
    "BuildRequirement",
    "ResolutionOutcome",
    "ResolvedRequirement",
    "SdistReaderError",
    "read_build_system_requires",
    "BuildResolver",
    "ResolverError",
]
