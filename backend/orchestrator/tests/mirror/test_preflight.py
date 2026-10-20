"""
Tests for preflight.

The preflight is the only module in `mirror` that shells out to
docker. Every test here mocks `asyncio.create_subprocess_exec`
and asserts the shape of what preflight asks for, not the result
of a real docker run.

The tests exercise:
  - cache miss / cache hit behavior
  - digest-keyed caching (a tag rename with the same digest hits
    the cache; a rebuild with a new digest invalidates)
  - builder/verifier mismatch
  - missing image
  - malformed output from docker
  - get_supported_tags returns the cached frozenset
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.mirror import preflight
from src.agents.mirror.preflight import (
    PreflightError,
    check_builder_verifier_match,
    get_supported_tags,
)


def _fake_proc(returncode=0, stdout=b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, None))
    return proc


def _inspect_payload(
    python="3.11.16",
    platform="linux_aarch64",
    tags=None,
):
    if tags is None:
        tags = [
            "cp311-cp311-manylinux_aarch64",
            "cp311-cp311-linux_aarch64",
            "py3-none-any",
        ]
    return json.dumps({
        "python": python,
        "platform": platform,
        "tags": tags,
    }).encode()


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    """Every test starts with an empty cache."""
    monkeypatch.setattr(preflight, "_cache", {})


@pytest.fixture
def docker_mock(monkeypatch):
    """
    Patch asyncio.create_subprocess_exec with a scriptable fake.

    Two docker subcommands are handled:

      `docker image inspect <image> --format {{.Id}}`
        → returns a synthetic digest, one per image name. If the
          image is not in the registry, returns exit=1 (missing
          image case).

      `docker run --rm --network none <image> python -c <script>`
        → returns an inspect payload derived from the image's
          registry entry: Python version, platform, and a small
          synthetic tag set.

    The registry maps image name → payload dict. A payload dict
    has at least "python" and "platform" keys. If absent, the
    image is treated as missing.

    The digest for each image is deterministic from the payload:
    `sha256:<hash of the payload's JSON>`. Two `install` calls
    with the same payload produce the same digest (cache hit);
    a different payload produces a different digest (cache miss).
    """
    calls: list[tuple[str, ...]] = []

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        if argv[0] != "docker":
            return _fake_proc(returncode=1, stdout=b"unexpected")

        if len(argv) >= 4 and argv[1] == "image" and argv[2] == "inspect":
            image = argv[3]
            info = images.get(image)
            if info is None:
                return _fake_proc(
                    returncode=1,
                    stdout=f"Error: No such image: {image}".encode(),
                )
            # Digest is deterministic from the payload — same
            # payload, same digest (cache hit); different
            # payload, different digest (cache miss).
            import hashlib, json as _json
            digest_source = _json.dumps(info, sort_keys=True).encode()
            digest = "sha256:" + hashlib.sha256(digest_source).hexdigest()
            return _fake_proc(returncode=0, stdout=digest.encode())

        if len(argv) >= 6 and argv[1] == "run":
            # argv: docker run --rm --network none <image> python -c <script>
            image = argv[5]
            info = images.get(image)
            if info is None:
                return _fake_proc(returncode=1, stdout=b"no image")
            return _fake_proc(
                returncode=0, stdout=_inspect_payload(**info),
            )

        return _fake_proc(returncode=1, stdout=b"unexpected")

    # Registry: image name → payload dict with python/platform,
    # and optionally tags.
    images: dict[str, dict] = {}

    def install(new_images: dict[str, dict | None]):
        images.clear()
        for name, spec in new_images.items():
            if spec is not None:
                images[name] = spec

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec", fake_exec,
    )
    return {"calls": calls, "install": install, "images": images}


# ── happy path ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_preflight_passes_when_images_agree(docker_mock):
    docker_mock["install"]({
        "aegis-builder:latest": {"python": "3.11.16", "platform": "linux_aarch64"},
        "aegis-verifier:latest": {"python": "3.11.16", "platform": "linux_aarch64"},
    })
    await check_builder_verifier_match()
    # Cache is populated.
    key = await preflight._cache_key()
    assert key in preflight._cache
    assert len(preflight._cache[key]["tags"]) > 0


@pytest.mark.asyncio
async def test_get_supported_tags_returns_frozenset(docker_mock):
    docker_mock["install"]({
        "aegis-builder:latest": {"python": "3.11.16", "platform": "linux_aarch64"},
        "aegis-verifier:latest": {"python": "3.11.16", "platform": "linux_aarch64"},
    })
    tags = await get_supported_tags()
    assert isinstance(tags, frozenset)
    assert "cp311-cp311-manylinux_aarch64" in tags
    assert "py3-none-any" in tags


# ── mismatch detection ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_python_version_mismatch_raises(docker_mock):
    docker_mock["install"]({
        "aegis-builder:latest": {"python": "3.11.16", "platform": "linux_aarch64"},
        "aegis-verifier:latest": {"python": "3.12.1", "platform": "linux_aarch64"},
    })
    with pytest.raises(PreflightError) as exc_info:
        await check_builder_verifier_match()
    assert exc_info.value.reason == "builder_verifier_mismatch"
    assert "3.11.16" in exc_info.value.detail
    assert "3.12.1" in exc_info.value.detail


@pytest.mark.asyncio
async def test_platform_mismatch_raises(docker_mock):
    docker_mock["install"]({
        "aegis-builder:latest": {"python": "3.11.16", "platform": "linux_aarch64"},
        "aegis-verifier:latest": {"python": "3.11.16", "platform": "linux_x86_64"},
    })
    with pytest.raises(PreflightError) as exc_info:
        await check_builder_verifier_match()
    assert exc_info.value.reason == "builder_verifier_mismatch"


# ── caching behavior ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_second_call_uses_cache(docker_mock):
    """
    The second call re-resolves the image digests (cheap, and
    required to detect a rebuild) but skips the docker run calls
    that gather the payload (expensive, one container per image).

    Asserting on docker run count rather than total docker count
    is the correct shape: digest resolution is not cached, by
    design. Caching it would mean a rebuild went undetected.
    """
    docker_mock["install"]({
        "aegis-builder:latest": {
            "python": "3.11.16", "platform": "linux_aarch64",
        },
        "aegis-verifier:latest": {
            "python": "3.11.16", "platform": "linux_aarch64",
        },
    })

    def run_calls():
        return [
            c for c in docker_mock["calls"]
            if len(c) > 1 and c[0] == "docker" and c[1] == "run"
        ]

    await check_builder_verifier_match()
    first_run_count = len(run_calls())
    assert first_run_count == 2  # one per image

    await check_builder_verifier_match()
    # The docker run calls should not have repeated.
    assert len(run_calls()) == first_run_count


@pytest.mark.asyncio
async def test_digest_change_invalidates_cache(docker_mock):
    """
    First run: both images agree, cache populated.

    Second run: the verifier image was rebuilt with a new Python
    version. Its digest changes, so the cache key changes, so the
    preflight re-runs and catches the mismatch.

    If the cache were keyed on tag names (aegis-verifier:latest)
    rather than digests, the second run would hit the stale cache
    and report success — that's the bug this test prevents.
    """
    # First run: both images agree.
    docker_mock["install"]({
        "aegis-builder:latest": {
            "python": "3.11.16", "platform": "linux_aarch64",
        },
        "aegis-verifier:latest": {
            "python": "3.11.16", "platform": "linux_aarch64",
        },
    })
    await check_builder_verifier_match()
    assert len(preflight._cache) == 1

    # The verifier was rebuilt with a new Python version.
    docker_mock["install"]({
        "aegis-builder:latest": {
            "python": "3.11.16", "platform": "linux_aarch64",
        },
        "aegis-verifier:latest": {
            "python": "3.12.0", "platform": "linux_aarch64",
        },
    })
    with pytest.raises(PreflightError) as exc_info:
        await check_builder_verifier_match()
    assert exc_info.value.reason == "builder_verifier_mismatch"
    assert "3.12.0" in exc_info.value.detail


# ── failure modes ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_image_raises(docker_mock):
    docker_mock["install"]({
        "aegis-builder:latest": {"python": "3.11.16", "platform": "linux_aarch64"},
        # verifier missing
    })
    with pytest.raises(PreflightError) as exc_info:
        await check_builder_verifier_match()
    assert exc_info.value.reason == "image_not_found"


@pytest.mark.asyncio
async def test_inspect_nonzero_exit_raises(docker_mock):
    """Image exists but the docker run fails."""
    async def fake_exec(*argv, **kwargs):
        if argv[0] == "docker" and argv[1] == "image" and argv[2] == "inspect":
            return _fake_proc(returncode=0, stdout=b"sha256:digest")
        if argv[0] == "docker" and argv[1] == "run":
            return _fake_proc(returncode=1, stdout=b"exit 1: broken")
        return _fake_proc(returncode=1)
    import asyncio as _asyncio
    mp = pytest.MonkeyPatch()
    mp.setattr(_asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(PreflightError) as exc_info:
        await check_builder_verifier_match()
    assert exc_info.value.reason == "image_inspect_failed"


@pytest.mark.asyncio
async def test_inspect_bad_json_raises(docker_mock):
    async def fake_exec(*argv, **kwargs):
        if argv[0] == "docker" and argv[1] == "image" and argv[2] == "inspect":
            return _fake_proc(returncode=0, stdout=b"sha256:digest")
        if argv[0] == "docker" and argv[1] == "run":
            return _fake_proc(returncode=0, stdout=b"not json")
        return _fake_proc(returncode=1)
    import asyncio as _asyncio
    mp = pytest.MonkeyPatch()
    mp.setattr(_asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(PreflightError) as exc_info:
        await check_builder_verifier_match()
    assert exc_info.value.reason == "image_inspect_failed"
    assert "bad JSON" in exc_info.value.detail


# ── args passed to docker ──────────────────────────────────────

@pytest.mark.asyncio
async def test_image_inspect_has_no_network(docker_mock):
    docker_mock["install"]({
        "aegis-builder:latest": {"python": "3.11.16", "platform": "linux_aarch64"},
        "aegis-verifier:latest": {"python": "3.11.16", "platform": "linux_aarch64"},
    })
    await check_builder_verifier_match()
    run_calls = [
        c for c in docker_mock["calls"]
        if c[0] == "docker" and len(c) > 1 and c[1] == "run"
    ]
    assert run_calls, "no docker run call was made"
    for call in run_calls:
        # --network none must be present
        assert "--network" in call
        idx = call.index("--network")
        assert call[idx + 1] == "none"


@pytest.mark.asyncio
async def test_inspect_runs_packaging_tags_script(docker_mock):
    docker_mock["install"]({
        "aegis-builder:latest": {"python": "3.11.16", "platform": "linux_aarch64"},
        "aegis-verifier:latest": {"python": "3.11.16", "platform": "linux_aarch64"},
    })
    await check_builder_verifier_match()
    run_calls = [
        c for c in docker_mock["calls"]
        if c[0] == "docker" and len(c) > 1 and c[1] == "run"
    ]
    # At least one of the run calls invokes the tag-list script.
    found_tag_script = False
    for call in run_calls:
        joined = " ".join(call)
        if "sys_tags" in joined or "packaging.tags" in joined:
            found_tag_script = True
            break
    assert found_tag_script, (
        f"no docker run invoked the tag-list script. "
        f"runs: {run_calls}"
    )
