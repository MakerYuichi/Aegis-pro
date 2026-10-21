"""
Integration tests for the verifier's baseline behavior.

These tests mock _run_in_docker and the repair loop so no
Docker or network is needed. They exercise:

  - with-diff run has no new failures → tests_passed_pre_existing
  - with-diff run has new failures → tests_failed, repair loop
  - baseline times out → fallback to old behavior
  - baseline has all failures → no repair fires
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.verifier import HostedVerifier


# Minimal fixtures reused across the tests
@pytest.fixture
def baseline_failures_output():
    return (
        "FAILED tests/test_db.py::test_conn - ConnectionRefused\n"
        "FAILED tests/test_db.py::test_query - ConnectionRefused\n"
        "===== 2 failed, 10 passed in 0.5s =====\n"
    )


@pytest.fixture
def with_diff_new_failure_output():
    return (
        "FAILED tests/test_db.py::test_conn - ConnectionRefused\n"
        "FAILED tests/test_db.py::test_query - ConnectionRefused\n"
        "FAILED tests/test_new.py::test_marker - AssertionError\n"
        "===== 3 failed, 10 passed in 0.5s =====\n"
    )


@pytest.fixture
def no_failures_output():
    return "===== 12 passed in 0.5s =====\n"


@pytest.fixture
def mock_prefetch():
    from src.agents.prefetch.receipt import PrefetchReceipt
    from src.agents.prefetch.runner import PrefetchResult
    from pathlib import Path

    receipt = PrefetchReceipt(
        manifest_path="requirements.txt",
        manifest_hash="sha256:" + "a" * 64,
        python_version="3.11.16",
        platform_tag="linux_aarch64",
        packages=[],
        fetched_now=True,
        duration_ms=100,
    )
    result = PrefetchResult(
        cache_container_path=Path("/cache"),
        cache_host_path=Path("/cache"),
        lock_path=Path("/cache/requirements.lock"),
        receipt=receipt,
    )
    return AsyncMock(return_value=result)


def _repo_workdir(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("")
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_smoke.py").write_text("def test_ok(): pass\n")
    return tmp_path


@pytest.mark.asyncio
async def test_pre_existing_failures_yield_passed_pre_existing(
    tmp_path, mock_prefetch, baseline_failures_output,
    with_diff_new_failure_output, no_failures_output,
):
    """With-diff run adds no new failures → passed_pre_existing."""
    workdir = _repo_workdir(tmp_path)

    async def fake_docker(*, command, **kwargs):
        # Both baseline and with-diff runs produce the same
        # failures. No new failures.
        return 1, baseline_failures_output

    with patch(
        "src.agents.verifier.run_prefetch_with_build_on_miss",
        mock_prefetch,
    ), patch(
        "src.agents.verifier.find_manifest",
    ) as find, patch(
        "src.agents.verifier._run_in_docker", fake_docker,
    ), patch(
        "src.agents.verifier._attempt_repair",
        AsyncMock(return_value=None),
    ):
        from src.agents.prefetch.manifest_finder import ManifestRef
        find.return_value = ManifestRef(
            path=__import__("pathlib").Path("requirements.txt"),
            kind="requirements",
        )
        v = HostedVerifier()
        result = await v.verify(
            repo_name="owner/repo",
            commit_sha="HEAD",
            diff=(
                "--- a/tests/test_smoke.py\n"
                "+++ b/tests/test_smoke.py\n"
                "@@ -1,1 +1,2 @@\n"
                " def test_ok(): pass\n"
                "+# baseline marker\n"
            ),
            language="Python",
            context={"repo_workdir": str(workdir)},
        )

    assert result.passed is True
    assert result.reason == "tests_passed_pre_existing_failures"


@pytest.mark.asyncio
async def test_new_failure_triggers_repair(
    tmp_path, mock_prefetch, baseline_failures_output,
    with_diff_new_failure_output,
):
    """With-diff run adds a new failure → repair loop fires."""
    workdir = _repo_workdir(tmp_path)
    call_count = {"n": 0}

    async def fake_docker(*, command, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Baseline
            return 1, baseline_failures_output
        # With diff
        return 1, with_diff_new_failure_output

    with patch(
        "src.agents.verifier.run_prefetch_with_build_on_miss",
        mock_prefetch,
    ), patch(
        "src.agents.verifier.find_manifest",
    ) as find, patch(
        "src.agents.verifier._run_in_docker", fake_docker,
    ), patch(
        "src.agents.verifier._attempt_repair",
        AsyncMock(return_value=None),  # repair fails, loop breaks
    ):
        from src.agents.prefetch.manifest_finder import ManifestRef
        find.return_value = ManifestRef(
            path=__import__("pathlib").Path("requirements.txt"),
            kind="requirements",
        )
        v = HostedVerifier()
        result = await v.verify(
            repo_name="owner/repo",
            commit_sha="HEAD",
            diff=(
                "--- a/tests/test_smoke.py\n"
                "+++ b/tests/test_smoke.py\n"
                "@@ -1,1 +1,2 @@\n"
                " def test_ok(): pass\n"
                "+# baseline marker\n"
            ),
            language="Python",
            context={"repo_workdir": str(workdir)},
        )

    assert result.passed is False
    assert result.reason == "tests_failed"


@pytest.mark.asyncio
async def test_no_failures_passes_normally(
    tmp_path, mock_prefetch, no_failures_output,
):
    """Baseline clean, with-diff clean → tests_passed."""
    workdir = _repo_workdir(tmp_path)

    async def fake_docker(*, command, **kwargs):
        return 0, no_failures_output

    with patch(
        "src.agents.verifier.run_prefetch_with_build_on_miss",
        mock_prefetch,
    ), patch(
        "src.agents.verifier.find_manifest",
    ) as find, patch(
        "src.agents.verifier._run_in_docker", fake_docker,
    ):
        from src.agents.prefetch.manifest_finder import ManifestRef
        find.return_value = ManifestRef(
            path=__import__("pathlib").Path("requirements.txt"),
            kind="requirements",
        )
        v = HostedVerifier()
        result = await v.verify(
            repo_name="owner/repo",
            commit_sha="HEAD",
            diff=(
                "--- a/tests/test_smoke.py\n"
                "+++ b/tests/test_smoke.py\n"
                "@@ -1,1 +1,2 @@\n"
                " def test_ok(): pass\n"
                "+# baseline marker\n"
            ),
            language="Python",
            context={"repo_workdir": str(workdir)},
        )

    assert result.passed is True
    assert result.reason == "tests_passed"
