"""
Prefetch: install the target repo's Python dependencies into a cache
so the verifier can run its tests offline.

The trust model, in one sentence: whatever has network never runs
AI-written code, and whatever runs AI-written code never has network.

Two phases:

  1. Prefetch (this package). A throwaway container with network,
     no secrets, no Docker socket. It reads the manifest, sanitizes
     it, downloads wheels into a shared cache, and writes a receipt
     to stdout. It never runs code from the repo.

  2. Verify (HostedVerifier, unchanged here). The existing sandbox
     with --network none. It installs from the cache with
     --no-index --require-hashes and runs the repo's tests. It never
     reaches the network.

Public surface:
    sanitize_manifest(path)         -> list[PackagePin] or raise
    route_pin(pin)                  -> IndexRoute
    run_prefetch(manifest_path, cache_dir)  -> PrefetchResult
    parse_receipt(stdout)           -> PrefetchReceipt or raise
"""
from src.agents.prefetch.sanitize import (
    PackagePin,
    SanitizeError,
    sanitize_manifest,
)
from src.agents.prefetch.policy import IndexRoute, PolicyError, route_pin
from src.agents.prefetch.runner import PrefetchResult, run_prefetch
from src.agents.prefetch.receipt import (
    PrefetchReceipt,
    ReceiptError,
    parse_receipt,
)

__all__ = [
    "PackagePin",
    "SanitizeError",
    "sanitize_manifest",
    "IndexRoute",
    "PolicyError",
    "route_pin",
    "PrefetchResult",
    "run_prefetch",
    "PrefetchReceipt",
    "ReceiptError",
    "parse_receipt",
]
