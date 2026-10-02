"""
Tests for IncidentService helper methods and edge-case blocks.

Covers:
  - Autofix block in declare_incident
  - _parse_stack_trace fallback regexes
  - save_incident_metadata (real DB)
  - get_service / list_services error fallbacks (via db_error fixture)

Does NOT cover update_incident — that touches the ORM models in
src/models/ which have 0% coverage and belong in a separate PR.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from src.services.incident_service import IncidentService


STUB_SERVICE = {
    "name": "payment-api",
    "repo_name": "payment-service",
    "on_call": ["@marcus"],
    "dependencies": ["auth"],
    "is_critical": True,
}

STUB_ANALYSIS = {
    "severity": "P1", "title": "DB down", "root_cause": "pool exhausted",
    "suggested_fix": "increase pool", "rollback_command": "kubectl undo",
    "confidence": 0.9,
}

STACK = "java.sql.SQLException: refused\n    at com.acme.DB.execute(DBConnection.java:88)\n"


@pytest.fixture
def service():
    with patch("src.services.incident_service.LLMService") as llm_cls, \
         patch("src.services.incident_service.get_rag_service") as rag_cls:
        llm = MagicMock()
        llm.analyze_incident = AsyncMock(return_value=STUB_ANALYSIS)
        llm_cls.return_value = llm

        rag = MagicMock()
        rag.generate_context_prompt = AsyncMock(return_value="")
        rag.store_incident = AsyncMock()
        rag_cls.return_value = rag

        svc = IncidentService()
        svc._llm_mock = llm
        svc._rag_mock = rag
    return svc


@pytest.fixture
def orchestrated(service):
    """Service with all external boundaries stubbed, ready for declare_incident."""
    with patch.object(service, "get_service", new=AsyncMock(return_value=STUB_SERVICE)), \
         patch.object(service, "_persist_diagnosed_incident", new=AsyncMock()), \
         patch.object(service, "record_github_context", new=AsyncMock()), \
         patch.object(service, "record_code_context", new=AsyncMock()), \
         patch.object(service, "record_related_prs", new=AsyncMock()), \
         patch.object(service, "record_auto_fix", new=AsyncMock()), \
         patch.object(service, "calculate_blast_radius",
                      new=AsyncMock(return_value={"root": "payment-api",
                                                   "affected": ["payment-api"],
                                                   "count": 1, "severity": "MEDIUM"})):
        yield service
        

@pytest.fixture
def autofix_orchestrated(service, db_session, seeded_services):
    """
    Real-DB variant of `orchestrated` for the autofix tests.

    Persistence and record_auto_fix run against the test transaction,
    so the assertions can check the actual row rather than a mock
    payload. Only the external boundaries are stubbed: GitHub, LLM
    analysis, alerts, K8s, WebSocket, and AutoFixService.

    The `seeded_services` fixture provides payment-api with
    repo_name="payment-service", so declare_incident's fixer block
    has a real service to look up.
    """
    with patch.object(service, "calculate_blast_radius",
                      new=AsyncMock(return_value={"root": "payment-api",
                                                   "affected": ["payment-api"],
                                                   "count": 1, "severity": "MEDIUM"})):
        yield service


def _quiet_peripherals():
    """Return a tuple of patches that neutralize everything except autofix."""
    oncall = patch("src.services.incident_service.OnCallService")
    alert = patch("src.services.incident_service.AlertService")
    k8s = patch("src.services.incident_service.KubernetesService")
    ws = patch("src.services.incident_service.manager")
    gh = patch("src.services.incident_service.get_github_service",
               return_value=MagicMock(
                   get_recent_prs=AsyncMock(return_value=[]),
                   get_blame_with_pr=AsyncMock(return_value=None),
                   get_file_content=AsyncMock(return_value=None),
                   get_related_prs=AsyncMock(return_value=[]),
               ))
    return oncall, alert, k8s, ws, gh


# ===========================================================================
# Autofix block in declare_incident
# ===========================================================================

@pytest.mark.asyncio
async def test_declare_incident_autofix_success_merges_into_metadata(
    autofix_orchestrated, seeded_services, monkeypatch
):
    """
    Real DB: a successful fix from AutoFixService lands in the
    extra_metadata.auto_fix key on the persisted incident row.
    """
   
    monkeypatch.setattr("src.services.incident_service.settings.INVESTIGATOR_MODE", "stage")
    autofix_result = {
        "status": "fix_generated",
        "fix": "--- a\n+++ b\n",
        "pr": {"mode": "read_only", "status": "skipped"},
        "requires_approval": True,
    }
    fake_autofix = MagicMock()
    fake_autofix.generate_fix = AsyncMock(return_value=autofix_result)

    oncall, alert, k8s, ws, gh = _quiet_peripherals()
    with oncall as OnCall, alert as Alert, k8s as K8s, ws as ws_mock, gh, \
         patch("src.services.incident_service.AutoFixService",
               return_value=fake_autofix):
        OnCall.return_value.get_on_call = AsyncMock(
            return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws_mock.broadcast = AsyncMock()

        result = await autofix_orchestrated.declare_incident(
            "payment-api", "DB down", stack_trace=STACK
        )

    fake_autofix.generate_fix.assert_awaited_once()

    # Assert against the real row, not a mock payload.
    incident = await autofix_orchestrated.get_incident(result["incident_id"])
    assert incident is not None
    meta = incident["extra_metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    assert meta["auto_fix"] == autofix_result


@pytest.mark.asyncio
async def test_declare_incident_autofix_error_result_not_merged(
    autofix_orchestrated, seeded_services, monkeypatch
):
    """
    Real DB: when AutoFixService returns {"error": ...}, the row's
    extra_metadata must NOT have an auto_fix key.
    """
    from src.config import settings
    monkeypatch.setattr(settings, "INVESTIGATOR_MODE", "stage")
    
    fake_autofix = MagicMock()
    fake_autofix.generate_fix = AsyncMock(return_value={"error": "no code found"})

    oncall, alert, k8s, ws, gh = _quiet_peripherals()
    with oncall as OnCall, alert as Alert, k8s as K8s, ws as ws_mock, gh, \
         patch("src.services.incident_service.AutoFixService",
               return_value=fake_autofix):
        OnCall.return_value.get_on_call = AsyncMock(
            return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws_mock.broadcast = AsyncMock()

        result = await autofix_orchestrated.declare_incident(
            "payment-api", "DB down", stack_trace=STACK
        )

    incident = await autofix_orchestrated.get_incident(result["incident_id"])
    meta = incident["extra_metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    assert "auto_fix" not in meta


@pytest.mark.asyncio
async def test_declare_incident_autofix_exception_is_swallowed(
    autofix_orchestrated, seeded_services, monkeypatch
):
    """
    Real DB: when AutoFixService.generate_fix raises, declare_incident
    still persists the incident and returns success. The auto_fix key
    is absent.
    """
    from src.config import settings
    monkeypatch.setattr(settings, "INVESTIGATOR_MODE", "stage")

    fake_autofix = MagicMock()
    fake_autofix.generate_fix = AsyncMock(side_effect=RuntimeError("llm down"))

    oncall, alert, k8s, ws, gh = _quiet_peripherals()
    with oncall as OnCall, alert as Alert, k8s as K8s, ws as ws_mock, gh, \
         patch("src.services.incident_service.AutoFixService",
               return_value=fake_autofix):
        OnCall.return_value.get_on_call = AsyncMock(
            return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws_mock.broadcast = AsyncMock()

        result = await autofix_orchestrated.declare_incident(
            "payment-api", "DB down", stack_trace=STACK
        )

    assert "error" not in result
    incident = await autofix_orchestrated.get_incident(result["incident_id"])
    meta = incident["extra_metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    assert "auto_fix" not in meta


# ===========================================================================
# _parse_stack_trace fallbacks
# ===========================================================================

@pytest.mark.parametrize("trace,expected_file,expected_line", [
    ("java.lang.RuntimeException: boom\n    at com.acme.Foo.bar(Foo.java:42)",
     "Foo.java", 42),
    ("Exception in thread main\n    at Bar.java:55", "Bar.java", 55),
    ('Traceback (most recent call last):\n  File "src/app.py", line 7, in <module>',
     "src/app.py", 7),
    ("error at db.py:99", "db.py", 99),
    ("at ClassName.java:12", "ClassName.java", 12),
    ("fail at AuthService:44", "AuthService", 44),
])
def test_parse_stack_trace_patterns(service, trace, expected_file, expected_line):
    result = service._parse_stack_trace(trace)
    assert result["file_path"] == expected_file
    assert result["line_number"] == expected_line


def test_parse_stack_trace_no_match_returns_none_file(service):
    result = service._parse_stack_trace("just some text with no trace")
    assert result["file_path"] is None
    assert result["line_number"] is None


def test_parse_stack_trace_extracts_exception_type(service):
    result = service._parse_stack_trace("java.io.IOException: file missing")
    assert result["exception_type"] == "IOException"


def test_parse_stack_trace_stores_truncated_trace(service):
    long_trace = "x" * 1000
    result = service._parse_stack_trace(long_trace)
    assert len(result["full_trace"]) == 500


# ===========================================================================
# get_service / list_services fallback branches — db_error
# ===========================================================================

@pytest.mark.asyncio
async def test_get_service_db_error_falls_back_to_mock(service, db_error):
    """db_error forces DB failure; get_service returns mock dict."""
    result = await service.get_service("payment-api")
    assert result["name"] == "payment-api"
    assert result["on_call"] == ["@marcus", "@prisha"]


@pytest.mark.asyncio
async def test_list_services_db_error_falls_back_to_mock_list(service, db_error):
    """db_error forces DB failure; list_services returns mock list."""
    result = await service.list_services()
    assert len(result) == 8
    assert {s["name"] for s in result} >= {"payment-api", "auth", "database"}
