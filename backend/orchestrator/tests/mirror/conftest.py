"""
Fixtures and markers for the mirror test suite.

The hostile fixture tests require Docker (they exercise the
build container and the smoke test's container import check)
and are marked `requires_docker`. They're skipped if Docker
isn't available. The existing test suite runs without Docker;
only the hostile suite needs it.
"""
from __future__ import annotations

import asyncio
import subprocess

import pytest


def _docker_available() -> bool:
    """
    Check whether the Docker CLI can reach the daemon.

    Uses `docker ps`, not `docker info`. The orchestrator reaches
    the daemon through the Tecnativa socket proxy, which blocks
    the /info endpoint (INFO: "0" in docker-compose.yml) but
    allows container operations (CONTAINERS: "1"). `docker info`
    fails through the proxy; `docker ps` succeeds.

    The tests need container operations, so `docker ps` is the
    right check. It fails for the same reasons container spawns
    would fail — daemon unreachable, proxy misconfigured, CLI
    missing — so a False result correlates with the tests
    actually being unrunnable, not with an unrelated health
    check being blocked.
    """
    try:
        result = subprocess.run(
            ["docker", "ps"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


_DOCKER_OK = _docker_available()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_docker: test needs a Docker daemon and the "
        "aegis-builder / aegis-verifier images",
    )


def pytest_collection_modifyitems(config, items):
    if _DOCKER_OK:
        return
    skip_marker = pytest.mark.skip(
        reason="Docker not available; hostile fixture tests skipped",
    )
    for item in items:
        if "requires_docker" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture
async def _assert_no_leaked_containers():
    """
    Fixture that, after the test, asserts no container named
    aegis-build-* or aegis-smoke-* remains. Catches the bug where
    a timeout or a crash leaves a container running.

    The check is best-effort: if docker ps itself fails, we don't
    fail the test for infrastructure reasons.
    """
    yield
    proc = await asyncio.create_subprocess_exec(
        "docker", "ps",
        "--filter", "name=aegis-build-",
        "--filter", "name=aegis-smoke-",
        "--format", "{{.Names}}",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    names = out.decode("utf-8").strip().splitlines()
    assert not names, (
        f"leaked containers after test: {names}"
    )
