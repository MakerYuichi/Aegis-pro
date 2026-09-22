"""
Tests for IncidentService helper methods and edge-case blocks.

Covers:
  - Autofix block in declare_incident (lines 129-160)
  - _parse_stack_trace fallback regexes (lines 522-550)
  - save_incident_metadata (lines 615-621)
  - get_service / list_services error fallbacks (lines 341-352)

Does NOT cover update_incident — that touches the ORM models in
src/models/ which have 0% coverage and belong in a separate PR.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.incident_service import IncidentService


@pytest.fixture
def service():
    with patch("src.services.incident_service.LLMService") as llm_cls, \
         patch("src.services.incident_service.RAGService") as rag_cls:
        llm = MagicMock()
        llm.analyze_incident = AsyncMock(return_value=STUB_ANALYSIS)
        llm_cls.return_value = llm

        rag = MagicMock()
        rag.generate_context_prompt = AsyncMock(return_value="")
        rag.store_incident = AsyncMock()
        rag_cls.return_value = rag

        svc = IncidentService()
        # Stash the mocks so tests can reconfigure them without re-patching.
        svc._llm_mock = llm
        svc._rag_mock = rag
    return svc


def _mock_db(session=None):
    if session is None:
        session = MagicMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

    async def _get_db():
        return session

    return _get_db, session


# ===========================================================================
# Autofix block in declare_incident
# ===========================================================================

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
def orchestrated(service):
    """Service with all external boundaries stubbed, ready for declare_incident."""
    get_db, session = _mock_db()
    with patch("src.services.incident_service.get_db", get_db), \
         patch.object(service, "get_service", new=AsyncMock(return_value=STUB_SERVICE)), \
         patch.object(service, "save_incident", new=AsyncMock()), \
         patch.object(service, "calculate_blast_radius",
                      new=AsyncMock(return_value={"root": "payment-api",
                                                   "affected": ["payment-api"],
                                                   "count": 1, "severity": "MEDIUM"})):
        service._llm_mock.analyze_incident = AsyncMock(return_value=STUB_ANALYSIS)
        service._rag_mock.generate_context_prompt = AsyncMock(return_value="")
        service._rag_mock.store_incident = AsyncMock()
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


@pytest.mark.asyncio
async def test_declare_incident_autofix_success_merges_into_metadata(orchestrated):
    """
    Situation: Auto-fix generates successfully.
    Expected: Auto-fix result merged into incident metadata.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
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
         patch("src.services.autofix_service.AutoFixService",
               return_value=fake_autofix):
        OnCall.return_value.get_on_call = AsyncMock(
            return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws_mock.broadcast = AsyncMock()

        await orchestrated.declare_incident(
            "payment-api", "DB down", stack_trace=STACK
        )

    fake_autofix.generate_fix.assert_awaited_once()
    saved = orchestrated.save_incident.await_args.args[0]
    metadata = json.loads(saved["extra_metadata"])
    assert metadata["auto_fix"] == autofix_result


@pytest.mark.asyncio
async def test_declare_incident_autofix_error_result_not_merged(orchestrated):
    """
    Situation: Auto-fix returns error.
    Expected: Auto-fix not merged into metadata.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    fake_autofix = MagicMock()
    fake_autofix.generate_fix = AsyncMock(return_value={"error": "no code found"})

    oncall, alert, k8s, ws, gh = _quiet_peripherals()
    with oncall as OnCall, alert as Alert, k8s as K8s, ws as ws_mock, gh, \
         patch("src.services.autofix_service.AutoFixService",
               return_value=fake_autofix):
        OnCall.return_value.get_on_call = AsyncMock(
            return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws_mock.broadcast = AsyncMock()

        await orchestrated.declare_incident(
            "payment-api", "DB down", stack_trace=STACK
        )

    saved = orchestrated.save_incident.await_args.args[0]
    metadata = json.loads(saved["extra_metadata"])
    assert "auto_fix" not in metadata


@pytest.mark.asyncio
async def test_declare_incident_autofix_exception_is_swallowed(orchestrated):
    """
    Situation: Auto-fix service raises exception.
    Expected: Exception caught, incident still created, auto-fix not in metadata.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    fake_autofix = MagicMock()
    fake_autofix.generate_fix = AsyncMock(side_effect=RuntimeError("llm down"))

    oncall, alert, k8s, ws, gh = _quiet_peripherals()
    with oncall as OnCall, alert as Alert, k8s as K8s, ws as ws_mock, gh, \
         patch("src.services.autofix_service.AutoFixService",
               return_value=fake_autofix):
        OnCall.return_value.get_on_call = AsyncMock(
            return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws_mock.broadcast = AsyncMock()

        result = await orchestrated.declare_incident(
            "payment-api", "DB down", stack_trace=STACK
        )

    # Incident still returns successfully
    assert "error" not in result
    saved = orchestrated.save_incident.await_args.args[0]
    metadata = json.loads(saved["extra_metadata"])
    assert "auto_fix" not in metadata


# ===========================================================================
# _parse_stack_trace fallbacks
# ===========================================================================

@pytest.mark.parametrize("trace,expected_file,expected_line", [
    # Java standard: at com.foo.Bar.method(File.java:123)
    ("java.lang.RuntimeException: boom\n    at com.acme.Foo.bar(Foo.java:42)",
     "Foo.java", 42),
    # Java short: at File.java:123
    ("Exception in thread main\n    at Bar.java:55", "Bar.java", 55),
    # Python: File "x.py", line 123
    ('Traceback (most recent call last):\n  File "src/app.py", line 7, in <module>',
     "src/app.py", 7),
    # Simple: file.py:123
    ("error at db.py:99", "db.py", 99),
    # Java class: ClassName.java:123
    ("at ClassName.java:12", "ClassName.java", 12),
    # Service: AuthService:123
    ("fail at AuthService:44", "AuthService", 44),
])
def test_parse_stack_trace_patterns(service, trace, expected_file, expected_line):
    """
    Situation: Various stack trace formats.
    Expected: Extracts file path and line number correctly.
    Function: src.services.incident_service.IncidentService._parse_stack_trace
    """
    result = service._parse_stack_trace(trace)
    assert result["file_path"] == expected_file
    assert result["line_number"] == expected_line


def test_parse_stack_trace_no_match_returns_none_file(service):
    """
    Situation: Stack trace with no recognizable pattern.
    Expected: Returns None for file and line.
    Function: src.services.incident_service.IncidentService._parse_stack_trace
    """
    result = service._parse_stack_trace("just some text with no trace")
    assert result["file_path"] is None
    assert result["line_number"] is None


def test_parse_stack_trace_extracts_exception_type(service):
    """
    Situation: Stack trace with exception type.
    Expected: Extracts exception type.
    Function: src.services.incident_service.IncidentService._parse_stack_trace
    """
    result = service._parse_stack_trace("java.io.IOException: file missing")
    assert result["exception_type"] == "IOException"


def test_parse_stack_trace_stores_truncated_trace(service):
    """
    Situation: Very long stack trace.
    Expected: Truncates to 500 chars in full_trace.
    Function: src.services.incident_service.IncidentService._parse_stack_trace
    """
    long_trace = "x" * 1000
    result = service._parse_stack_trace(long_trace)
    assert len(result["full_trace"]) == 500


# ===========================================================================
# save_incident_metadata
# ===========================================================================

@pytest.mark.asyncio
async def test_save_incident_metadata_writes_json(service):
    """
    Situation: Valid metadata to save.
    Expected: Writes JSON to DB, commits.
    Function: src.services.incident_service.IncidentService.save_incident_metadata
    """
    get_db, session = _mock_db()
    with patch("src.services.incident_service.get_db", get_db):
        result = await service.save_incident_metadata(
            "INC-1", {"auto_fix": {"status": "approved"}}
        )

    assert result == {"status": "updated", "incident_id": "INC-1"}
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_incident_metadata_db_error_returns_error_dict(service):
    """
    Situation: DB write fails.
    Expected: Returns error dict.
    Function: src.services.incident_service.IncidentService.save_incident_metadata
    """
    get_db, session = _mock_db()
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    with patch("src.services.incident_service.get_db", get_db):
        result = await service.save_incident_metadata("INC-1", {})

    assert "error" in result
    assert "db down" in result["error"]


# ===========================================================================
# get_service / list_services fallback branches
# ===========================================================================

@pytest.mark.asyncio
async def test_get_service_db_error_falls_back_to_mock(service):
    """
    Situation: DB query fails.
    Expected: Falls back to mock service dict.
    Function: src.services.incident_service.IncidentService.get_service
    """
    get_db, session = _mock_db()
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    with patch("src.services.incident_service.get_db", get_db):
        result = await service.get_service("payment-api")

    assert result["name"] == "payment-api"
    assert result["on_call"] == ["@marcus", "@prisha"]


@pytest.mark.asyncio
async def test_list_services_db_error_falls_back_to_mock_list(service):
    """
    Situation: DB query fails.
    Expected: Falls back to mock services list.
    Function: src.services.incident_service.IncidentService.list_services
    """
    get_db, session = _mock_db()
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    with patch("src.services.incident_service.get_db", get_db):
        result = await service.list_services()

    assert len(result) == 8
    assert {s["name"] for s in result} >= {"payment-api", "auth", "database"}
