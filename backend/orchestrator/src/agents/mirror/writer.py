"""
Publish a built wheel to the mirror.

Layout: <mirror>/wheels/<sdist-sha256>/

Atomic publish: the wheel and manifest are written to a temp
directory inside the mirror, then os.rename'd into place. A crash
mid-publish leaves a temp dir that's invisible to the lookup, not
a half-populated directory that later runs would trust.

Every manifest is written with the full build record — sdist URL
and hash, builder image, resolved build requirements, wheel hash,
and timestamps. That's the audit trail.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from loguru import logger

from src.agents.mirror.build import BuildOutput
from src.agents.mirror.types import ResolvedRequirement, SdistRef
from src.config import settings


class PublishError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else detail or reason)


def publish_built_wheel(
    *,
    built: BuildOutput,
    sdist_ref: SdistRef,
    requires: list[ResolvedRequirement],
    mirror_host_dir: Path,
) -> Path:
    """
    Publish to <mirror>/wheels/<sha256-of-sdist>/.

    Returns the host-side path of the published directory, which is
    the same value the prefetcher uses with --find-links on retry.
    """
    digest = sdist_ref.sha256.replace("sha256:", "")
    target_dir = mirror_host_dir / "wheels" / digest

    if target_dir.is_dir():
        # Already published. Idempotent.
        logger.info(
            f"publish: {sdist_ref.name} {sdist_ref.version} "
            f"already in mirror at {target_dir}"
        )
        return target_dir

    # Build the temp directory adjacent to the target so that
    # os.rename is guaranteed to be on the same filesystem.
    mirror_host_dir.mkdir(parents=True, exist_ok=True)
    staging_parent = mirror_host_dir / "wheels"
    staging_parent.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(
        prefix=".tmp-", dir=staging_parent,
    ))

    try:
        # Copy the validated wheel into the staging directory.
        # Copy, not move: the source is in a temp workdir that
        # the caller manages.
        wheel_dst = staging / built.wheel_path.name
        shutil.copy2(built.wheel_path, wheel_dst)

        # Write the build manifest.
        manifest = {
            "schema_version": 1,
            "sdist": {
                "url": sdist_ref.url,
                "filename": sdist_ref.filename,
                "sha256": sdist_ref.sha256,
                "name": sdist_ref.name,
                "version": sdist_ref.version,
                "upload_time": sdist_ref.upload_time,
            },
            "build": {
                "image": settings.BUILD_CONTAINER_IMAGE,
                "image_digest": _image_digest_or_empty(
                    settings.BUILD_CONTAINER_IMAGE,
                ),
                "started_at": _now_iso(),
                "python_version": _current_py_version(),
                "platform_tag": _current_platform(),
            },
            "build_requirements": [
                {
                    "name": r.name,
                    "version": r.version,
                    "requested": r.requested.raw_line,
                    "source_index": r.source_index,
                    "fallback_used": r.fallback_used,
                    "sha256": r.sha256,
                }
                for r in requires
            ],
            "wheel": {
                "filename": wheel_dst.name,
                "sha256": built.wheel_sha256,
                "size_bytes": built.wheel_size_bytes,
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        # Atomic rename into place.
        os.rename(staging, target_dir)
        logger.info(f"publish: published to {target_dir}")
        return target_dir

    except Exception:
        # Clean up staging on any failure.
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _current_py_version() -> str:
    import platform
    return platform.python_version()


def _current_platform() -> str:
    import platform
    return (
        platform.system().lower() + "_" +
        platform.machine().lower()
    )


def _image_digest_or_empty(image: str) -> str:
    """
    Best-effort lookup of an image's digest. The writer doesn't
    have an async context, so it shells out synchronously. If it
    fails, the manifest records an empty digest rather than failing
    the publish — the wheel and sdist hashes are the load-bearing
    audit trail.
    """
    try:
        import subprocess
        out = subprocess.check_output(
            ["docker", "image", "inspect", image,
             "--format", "{{.Id}}"],
            timeout=5, stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8").strip()
    except Exception:
        return ""
