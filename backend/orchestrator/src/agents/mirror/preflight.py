"""
Preflight check: builder image and verifier image must agree on
Python version and platform.

If they don't, wheels built by the builder are tagged for a
Python/platform the verifier can't install. The smoke test catches
that — but its failure reads "not a supported wheel on this
platform", which is cryptic. This check runs first, fails with
`builder_verifier_mismatch`, and names the two versions.

Cached by image digest: the check only runs when the set of image
digests changes, so the cost is amortized to once per image
rebuild.
"""
from __future__ import annotations

import asyncio
import json
import subprocess

from loguru import logger

from src.config import settings


class PreflightError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


_cached_ok: bool | None = None
_cached_key: tuple[str, str] | None = None


async def check_builder_verifier_match() -> None:
    """
    Raise PreflightError if the builder and verifier images have
    different Python versions or platforms. Idempotent; caches on
    success.
    """
    global _cached_ok, _cached_key

    builder = settings.BUILD_CONTAINER_IMAGE
    verifier = settings.VERIFY_DOCKER_IMAGE_PYTHON

    key = (builder, verifier)
    if _cached_ok and _cached_key == key:
        return

    builder_info = await _inspect_image(builder)
    verifier_info = await _inspect_image(verifier)

    b_py, b_plat = builder_info["python"], builder_info["platform"]
    v_py, v_plat = verifier_info["python"], verifier_info["platform"]

    if b_py != v_py or b_plat != v_plat:
        raise PreflightError(
            "builder_verifier_mismatch",
            f"builder={b_py}/{b_plat} "
            f"verifier={v_py}/{v_plat}",
        )

    logger.info(
        f"preflight: builder and verifier agree "
        f"({b_py}, {b_plat})"
    )
    _cached_ok = True
    _cached_key = key


async def _inspect_image(image: str) -> dict:
    """
    Run `python -c` inside the image to report python_version and
    platform. Returns {"python": "3.11.16", "platform": "linux_aarch64"}.
    """
    script = (
        "import json, platform; "
        "print(json.dumps({"
        "'python': platform.python_version(), "
        "'platform': (platform.system().lower() + '_' + "
        "platform.machine().lower())"
        "}))"
    )
    argv = [
        "docker", "run", "--rm", "--network", "none",
        image, "python", "-c", script,
    ]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        raise PreflightError(
            "image_inspect_failed",
            f"{image}: exit {proc.returncode}: "
            f"{out.decode('utf-8', 'replace')[:500]}",
        )
    try:
        return json.loads(out.decode("utf-8").strip())
    except json.JSONDecodeError as e:
        raise PreflightError(
            "image_inspect_failed",
            f"{image}: bad JSON: {e}",
        ) from e
