#!/usr/bin/env python3
"""
Build entrypoint. Runs inside the offline build container.

Stdlib only. The container has --network none, no secrets, no
docker socket, and no route to internal ranges. It runs the
sdist's setup.py / PEP 517 build hook, which is arbitrary code
from a repo we don't control. The container's only purpose is to
turn an sdist into a wheel and hand it back through the mounted
output directory.

Contract with the orchestrator:
  - Reads /build/source.tar.gz (read-only mount, the sdist)
  - Reads /wheelhouse/*.whl (read-only mount, build requirements)
  - Writes the built wheel into /build/out/ (read-write mount,
    fresh per run, created by the orchestrator)

Everything the orchestrator needs to verify is checked by the
orchestrator after this container exits: it validates /build/out
contents, runs the smoke test, and only publishes after both pass.
This script's job is narrow — build a wheel, exit. Its stdout is
display-only; the orchestrator decides from the exit code and the
validated artifact.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tarfile
from pathlib import Path


SOURCE_PATH = Path("/build/source.tar.gz")
# Extract into /tmp rather than /build/source. /build is on the
# read-only root filesystem (the container runs --read-only), so
# only the explicitly-mounted paths are writable. /tmp is a tmpfs
# mount added by the orchestrator's _build_argv, so it's writable
# and memory-backed.
SOURCE_DIR = Path("/tmp/build/source")
WHEELHOUSE = Path("/wheelhouse")
OUT_DIR = Path("/build/out")


def main() -> int:
    if not SOURCE_PATH.is_file():
        print(f"source_not_found: {SOURCE_PATH}", file=sys.stderr)
        return 2

    if not OUT_DIR.is_dir():
        OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Create the extraction directory. /tmp is a tmpfs mount
    # added by the orchestrator; /build is read-only.
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)

    # Extract with filter="data"
    # (available in 3.11 via the filter argument in 3.11.4+). This
    # strips absolute paths, refuses path traversal, and rejects
    # device files. The reader has already validated the tarball's
    # pyproject member; the extractor's job is defensive.
    try:
        with tarfile.open(SOURCE_PATH, "r:*") as tf:
            tf.extractall(path=SOURCE_DIR, filter="data")
    except tarfile.TarError as e:
        print(f"extract_failed: {e}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"extract_failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 3

    # Find the extracted root. Sdists have exactly one top-level
    # directory, named `<name>-<version>`.
    entries = [p for p in SOURCE_DIR.iterdir() if p.is_dir()]
    if len(entries) != 1:
        print(
            f"unexpected_sdist_layout: {len(entries)} top-level dirs",
            file=sys.stderr,
        )
        return 3
    project_dir = entries[0]

    # Run the wheel build. --no-index --find-links ensures no
    # network access; pip can only see the wheelhouse. pip's
    # build isolation is on, so it creates a fresh env for the
    # build backend and installs it from the wheelhouse.
    argv = [
        sys.executable, "-m", "pip", "wheel",
        "--no-deps",
        "--no-index",
        "--find-links", str(WHEELHOUSE),
        "--wheel-dir", str(OUT_DIR),
        str(project_dir),
    ]
    proc = subprocess.run(
        argv, capture_output=True, text=True, timeout=600,
    )

    # Log pip's output for the orchestrator's diagnosis. The
    # orchestrator uses the exit code to decide; this output is
    # display-only and truncated by the caller.
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)

    if proc.returncode != 0:
        return 4

    # Sanity check: exactly one wheel landed. More than one is
    # unexpected and should be refused by the orchestrator;
    # reporting it here makes the failure diagnosable.
    wheels = list(OUT_DIR.glob("*.whl"))
    if len(wheels) != 1:
        print(
            f"unexpected_wheel_count: {len(wheels)} files in "
            f"{OUT_DIR}",
            file=sys.stderr,
        )
        return 5

    return 0


if __name__ == "__main__":
    sys.exit(main())
