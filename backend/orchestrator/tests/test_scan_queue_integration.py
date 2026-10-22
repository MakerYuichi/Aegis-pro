"""
Test that scan_repo feeds both the report tier and the queue tier
into the pipeline, subject to SCANNER_MAX_INCIDENTS.

The queue tier is where unchecked_optional_attr candidates land.
Before this change, those were silently skipped.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.services.incident_service import IncidentService


@pytest.mark.asyncio
async def test_scan_repo_processes_report_and_queue(monkeypatch):
    monkeypatch.setattr(
        "src.services.incident_service.settings.SCANNER_MAX_INCIDENTS",
        10,
    )

    # Fake ScanResult with 2 report candidates and 3 queue candidates.
    from types import SimpleNamespace
    report = [
        SimpleNamespace(candidate=SimpleNamespace(
            root_file="a.py", root_line=1, symbol="x",
            pattern="bare_except",
            to_dict=lambda: {}),
            destination="report", score=0.5, reasoning="", chain=None),
        SimpleNamespace(candidate=SimpleNamespace(
            root_file="b.py", root_line=2, symbol="y",
            pattern="bare_except",
            to_dict=lambda: {}),
            destination="report", score=0.5, reasoning="", chain=None),
    ]
    queue = [
        SimpleNamespace(candidate=SimpleNamespace(
            root_file="c.py", root_line=3, symbol="z",
            pattern="unchecked_optional_attr",
            to_dict=lambda: {}),
            destination="investigator", score=0.15, reasoning="", chain=None),
        SimpleNamespace(candidate=SimpleNamespace(
            root_file="d.py", root_line=4, symbol="w",
            pattern="unchecked_optional_attr",
            to_dict=lambda: {}),
            destination="investigator", score=0.15, reasoning="", chain=None),
        SimpleNamespace(candidate=SimpleNamespace(
            root_file="e.py", root_line=5, symbol="v",
            pattern="unchecked_optional_attr",
            to_dict=lambda: {}),
            destination="investigator", score=0.15, reasoning="", chain=None),
    ]
    fake_scan_result = SimpleNamespace(
        report=report,
        investigator_queue=queue,
        files_scanned=5,
        to_dict=lambda: {"counts": {"report": 2, "investigator": 3}},
    )

    with patch(
        "src.scanner.scan_runner.run_scan",
        return_value=fake_scan_result,
    ), patch(
        "src.agents.repo_clone.clone_repo",
        AsyncMock(return_value=("/tmp/fake", None)),
    ), patch(
        "src.agents.repo_clone.cleanup_repo",
    ), patch.object(
        IncidentService, "resolve_scan_service",
        AsyncMock(return_value="test-svc"),
    ):
        svc = IncidentService()
        call_count = {"n": 0}

        async def fake_scan_single(self, *, outcome, repo_path, service_name):
            call_count["n"] += 1
            return {"incident_id": f"INC-{call_count['n']}"}

        with patch.object(
            IncidentService, "scan_single_candidate", fake_scan_single,
        ):
            result = await svc.scan_repo("owner/repo")

    # All 5 candidates were processed: 2 report + 3 queue.
    assert call_count["n"] == 5
    assert len(result["incident_ids"]) == 5


@pytest.mark.asyncio
async def test_scan_repo_budget_caps_total_processing(monkeypatch):
    monkeypatch.setattr(
        "src.services.incident_service.settings.SCANNER_MAX_INCIDENTS",
        3,
    )

    from types import SimpleNamespace
    report = [
        SimpleNamespace(candidate=SimpleNamespace(
            root_file=f"r{i}.py", root_line=i, symbol="s",
            pattern="bare_except", to_dict=lambda: {}),
            destination="report", score=0.5, reasoning="", chain=None)
        for i in range(2)
    ]
    queue = [
        SimpleNamespace(candidate=SimpleNamespace(
            root_file=f"q{i}.py", root_line=i, symbol="s",
            pattern="unchecked_optional_attr", to_dict=lambda: {}),
            destination="investigator", score=0.15, reasoning="", chain=None)
        for i in range(5)
    ]
    fake_scan_result = SimpleNamespace(
        report=report,
        investigator_queue=queue,
        files_scanned=7,
        to_dict=lambda: {"counts": {"report": 2, "investigator": 5}},
    )

    with patch(
        "src.scanner.scan_runner.run_scan", return_value=fake_scan_result,
    ), patch(
        "src.agents.repo_clone.clone_repo",
        AsyncMock(return_value=("/tmp/fake", None)),
    ), patch(
        "src.agents.repo_clone.cleanup_repo",
    ), patch.object(
        IncidentService, "resolve_scan_service",
        AsyncMock(return_value="test-svc"),
    ):
        svc = IncidentService()
        call_count = {"n": 0}

        async def fake_scan_single(self, *, outcome, repo_path, service_name):
            call_count["n"] += 1
            return {"incident_id": f"INC-{call_count['n']}"}

        with patch.object(
            IncidentService, "scan_single_candidate", fake_scan_single,
        ):
            result = await svc.scan_repo("owner/repo")

    # Budget of 3: 2 report + 1 queue processed.
    assert call_count["n"] == 3
    assert len(result["incident_ids"]) == 3
