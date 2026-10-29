"""Test that scan_repo accepts a local directory as a scan target.

The CLI's normal path is owner/repo or a URL. The local-path path
was added for two reasons:

  1. CI and acceptance tests already have a checkout. Cloning it
     again wastes time and requires network.
  2. A developer running `aegis scan .` should work — scanning the
     current directory is the most natural invocation.

The contract: if repo_input is a directory that exists on disk, scan
it in place. If it's a repo identifier, clone as before.

The test does not exercise the actual scan pipeline (that's covered
by test_scan_queue_integration.py). It asserts the clone-vs-local
branching: run_scan is called with the local path, cleanup_repo is
not called, and effective_service defaults to the directory name.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.services.incident_service import IncidentService


@pytest.mark.asyncio
async def test_scan_repo_accepts_local_directory(tmp_path):
    """A path to an existing directory is scanned in place, no clone."""
    # A minimal fake repo layout.
    repo_dir = tmp_path / "my-project"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("x = 1\n")

    fake_scan_result = SimpleNamespace(
        report=[],
        investigator_queue=[],
        already_fixed=[],
        dropped={},
        files_scanned=1,
        duration_ms=0,
        repo=str(repo_dir),
        to_dict=lambda: {"counts": {"report": 0, "investigator": 0}},
    )

    with patch(
        "src.scanner.scan_runner.run_scan",
        return_value=fake_scan_result,
    ) as mock_run_scan, patch(
        "src.agents.repo_clone.clone_repo",
    ) as mock_clone, patch(
        "src.agents.repo_clone.cleanup_repo",
    ) as mock_cleanup, patch.object(
        IncidentService, "resolve_scan_service",
        AsyncMock(return_value="test-svc"),
    ):
        svc = IncidentService()
        result = await svc.scan_repo(str(repo_dir))

    # run_scan was called with the local path (or a resolved form).
    assert mock_run_scan.called
    call_path = mock_run_scan.call_args.args[0]
    assert str(call_path).endswith("my-project")

    # clone was never called — this is the whole point.
    mock_clone.assert_not_called()

    # cleanup was never called — we didn't create anything to clean up.
    mock_cleanup.assert_not_called()


@pytest.mark.asyncio
async def test_scan_repo_local_path_defaults_service_to_dirname(tmp_path):
    """When no service_name is given, the directory basename is used.

    The local-path branch also calls resolve_scan_service to ensure the
    service exists in the DB. Without that call, _stage_watcher's
    get_service returns None for every candidate and the pipeline
    silently produces zero incidents.
    """
    repo_dir = tmp_path / "awesome-project"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("x = 1\n")

    fake_scan_result = SimpleNamespace(
        report=[],
        investigator_queue=[],
        already_fixed=[],
        dropped={},
        files_scanned=1,
        duration_ms=0,
        repo=str(repo_dir),
        to_dict=lambda: {"counts": {"report": 0, "investigator": 0}},
    )

    captured: dict = {}

    async def fake_scan_single(self, *, outcome, repo_path, service_name):
        captured["service_name"] = service_name
        return {"incident_id": "INC-1"}

    # Need at least one candidate so scan_single_candidate is called.
    from src.scanner.candidate import PatternMatch, ScanCandidate, ChainResult, CHAIN_TRACED

    fake_match = PatternMatch(
        file="main.py", line=1, symbol="x",
        pattern="bare_except", confidence="medium",
        requires_chain=False,
    )
    fake_chain = ChainResult(status=CHAIN_TRACED, chain=[], terminal_kind="Unknown")
    fake_candidate = ScanCandidate(
        root_file="main.py", root_line=1, symbol="x",
        pattern="bare_except",
        chain=[], chain_status=CHAIN_TRACED, chain_depth=0,
        score=0.5, reasoning="test",
    )
    fake_outcome = SimpleNamespace(
        destination="report",
        candidate=fake_candidate,
        match=fake_match,
        chain=fake_chain,
        score=0.5,
        reasoning="test",
    )
    fake_scan_result = SimpleNamespace(
        report=[fake_outcome],
        investigator_queue=[],
        already_fixed=[],
        dropped={},
        files_scanned=1,
        duration_ms=0,
        repo=str(repo_dir),
        to_dict=lambda: {"counts": {"report": 1, "investigator": 0}},
    )

    with patch(
        "src.scanner.scan_runner.run_scan",
        return_value=fake_scan_result,
    ), patch(
        "src.agents.repo_clone.clone_repo",
    ) as mock_clone, patch(
        "src.agents.repo_clone.cleanup_repo",
    ), patch.object(
        IncidentService, "scan_single_candidate", fake_scan_single,
    ), patch.object(
        IncidentService, "resolve_scan_service",
        AsyncMock(return_value="should-not-be-used"),
    ) as mock_resolve:
        svc = IncidentService()
        await svc.scan_repo(str(repo_dir))

    mock_clone.assert_not_called()
    # Local paths DO call resolve_scan_service — without it, the service
    # row is never created in the DB, and _stage_watcher's get_service
    # returns None for every candidate. That was the bug this test was
    # originally guarding against; the guard flipped when the fix landed.
    #
    # Fix A added a repo_name kwarg: scan_repo reads .git/config to
    # learn the GitHub origin and passes it through. For a bare
    # directory with no .git/, repo_name is None (nothing to
    # enrich against), which is exactly what this tmp_path fixture
    # produces.
    mock_resolve.assert_called_once_with("awesome-project", repo_name=None)
    assert captured["service_name"] == "awesome-project"


@pytest.mark.asyncio
async def test_scan_repo_remote_path_still_clones(tmp_path):
    """A repo identifier (owner/repo) still clones. Regression test."""
    fake_scan_result = SimpleNamespace(
        report=[],
        investigator_queue=[],
        already_fixed=[],
        dropped={},
        files_scanned=0,
        duration_ms=0,
        repo="owner/repo",
        to_dict=lambda: {"counts": {"report": 0, "investigator": 0}},
    )

    with patch(
        "src.scanner.scan_runner.run_scan",
        return_value=fake_scan_result,
    ), patch(
        "src.agents.repo_clone.clone_repo",
        AsyncMock(return_value=("/tmp/fake", None)),
    ) as mock_clone, patch(
        "src.agents.repo_clone.cleanup_repo",
    ) as mock_cleanup, patch.object(
        IncidentService, "resolve_scan_service",
        AsyncMock(return_value="owner-repo"),
    ):
        svc = IncidentService()
        await svc.scan_repo("owner/repo")

    mock_clone.assert_called_once()
    mock_cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_scan_repo_nonexistent_local_path_clones(tmp_path):
    """A path that doesn't exist is treated as a repo identifier.

    A directory name that looks like owner/repo but doesn't exist
    on disk falls through to the clone path. If the clone fails
    (because the repo doesn't exist on GitHub), the caller sees a
    RuntimeError with a clear message.
    """
    nonexistent = tmp_path / "does-not-exist"

    with patch(
        "src.agents.repo_clone.clone_repo",
        AsyncMock(return_value=(None, "not a repo")),
    ) as mock_clone, patch.object(
        IncidentService, "resolve_scan_service",
        AsyncMock(return_value="x"),
    ):
        svc = IncidentService()
        with pytest.raises(RuntimeError, match="Could not clone"):
            await svc.scan_repo(str(nonexistent))

    mock_clone.assert_called_once()
