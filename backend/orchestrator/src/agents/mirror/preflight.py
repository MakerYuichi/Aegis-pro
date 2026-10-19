"""
Preflight: verify that builder and verifier images agree on
Python version and platform, and cache the verifier's supported
wheel tag set.

If the two images disagree on Python version or platform, wheels
built by the builder are tagged for something the verifier can't
install. The smoke test catches that — but its failure reads "not
a supported wheel on this platform", which is cryptic. This check
runs first, fails with `builder_verifier_mismatch`, and names the
two versions.

The tag set is what the smoke test uses to refuse a wheel whose
filename doesn't match any tag the verifier supports. It comes
from `packaging.tags.sys_tags()` executed inside the verifier
image — the same set pip itself uses — so the orchestrator and
pip agree on what "compatible" means.

Caching:

  - The check runs once per (builder_digest, verifier_digest).
    Digests are resolved via `docker image inspect --format
    {{.Id}}`. A rebuild changes the digest, which invalidates
    the cache. A tag rename (aegis-verifier:latest to something
    else) does not invalidate — the underlying image is the same.

  - The cache holds the tag set, the Python version, and the
    platform string. All three are immutable facts about a
    specific image digest.
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


# The cache. Keyed by (builder_digest, verifier_digest). Value is
# a dict with the tag set (frozenset of str) and the verifier's
# python and platform strings.
#
# In tests this is replaced wholesale (the test monkeypatches
# _cache to a fresh dict before each test).
_cache: dict[tuple[str, str], dict] = {}


async def get_supported_tags() -> frozenset[str]:
    """
    Return the set of wheel tag strings the verifier image supports.

    Runs the preflight if the cache is cold, returns the cached
    set otherwise. Raises PreflightError on infrastructure
    failure — same contract as check_builder_verifier_match.
    """
    await check_builder_verifier_match()
    key = await _cache_key()
    return _cache[key]["tags"]


async def check_builder_verifier_match() -> None:
    """
    Ensure builder and verifier images agree on Python version and
    platform. Caches the tag set alongside.
    """
    builder = settings.BUILD_CONTAINER_IMAGE
    verifier = settings.VERIFY_DOCKER_IMAGE_PYTHON

    key = await _cache_key()
    if key in _cache:
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
        f"({b_py}, {b_plat}); "
        f"{len(verifier_info['tags'])} verifier tags cached"
    )
    _cache[key] = {
        "python": v_py,
        "platform": v_plat,
        "tags": frozenset(verifier_info["tags"]),
    }


async def _cache_key() -> tuple[str, str]:
    """
    Resolve both image names to their content-addressed digests.

    If an image doesn't exist, `docker image inspect` exits
    nonzero and we raise PreflightError. The failure is at the
    point of the mistake — an unbuilt image — rather than three
    calls deep inside the tag lookup.
    """
    builder = settings.BUILD_CONTAINER_IMAGE
    verifier = settings.VERIFY_DOCKER_IMAGE_PYTHON

    builder_digest = await _resolve_digest(builder)
    verifier_digest = await _resolve_digest(verifier)
    return (builder_digest, verifier_digest)


async def _resolve_digest(image: str) -> str:
    argv = [
        "docker", "image", "inspect", image,
        "--format", "{{.Id}}",
    ]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        raise PreflightError(
            "image_not_found",
            f"{image}: {out.decode('utf-8', 'replace')[:200]}",
        )
    return out.decode("utf-8").strip()


async def _inspect_image(image: str) -> dict:
    """
    Run a script inside the image that reports:
      - python_version       ("3.11.16")
      - platform             ("linux_aarch64")
      - tags                 (list of wheel tag strings)

    The tag list comes from packaging.tags.sys_tags() — the same
    ordering pip uses. It's cached by the caller keyed on image
    digest; running this command is the expensive step (a docker
    run per image), and it happens once per (builder, verifier)
    digest pair.

    Hardening: --network none, no mounts, minimal. The container
    runs no untrusted code, but the same discipline applies as
    everywhere else in this codebase.
    """
    script = (
        "import json, platform\n"
        "from packaging.tags import sys_tags\n"
        "print(json.dumps({\n"
        "    'python': platform.python_version(),\n"
        "    'platform': (platform.system().lower() + '_' + "
        "platform.machine().lower()),\n"
        "    'tags': [str(t) for t in sys_tags()],\n"
        "}))\n"
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
        payload = json.loads(out.decode("utf-8").strip())
    except json.JSONDecodeError as e:
        raise PreflightError(
            "image_inspect_failed",
            f"{image}: bad JSON: {e}",
        ) from e

    for key in ("python", "platform", "tags"):
        if key not in payload:
            raise PreflightError(
                "image_inspect_failed",
                f"{image}: missing key {key!r}",
            )
    if not isinstance(payload["tags"], list):
        raise PreflightError(
            "image_inspect_failed",
            f"{image}: tags is not a list",
        )
    return payload
