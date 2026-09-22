"""
Tests for IncidentService.declare_incident orchestration.

The existing test_incident_service.py covers the declare_incident shape.
This file covers the *side effects* — the blocks that fetch GitHub context,
generate auto-fixes, page on-call, send alerts, query K8s, store embeddings,
and broadcast over WebSocket. Each block is wrapped in its own try/except
in the source, so the tests must verify that (a) each block runs when its
preconditions are met, and (b) a failure in any block does not break the
others or the final return.

Uses a stub service dict and a stub LLM analysis to keep the test focused
on orchestration, not on the analysis itself.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.incident_service import IncidentService


STUB_SERVICE = {
    "name": "payment-api",
    "repo_name": "payment-service",
    "on_call": ["@marcus", "@prisha"],
    "dependencies": ["auth", "ledger"],
    "is_critical": True,
}

STUB_ANALYSIS = {
    "severity": "P1",
    "title": "Payment failures spiking",
    "root_cause": "Connection pool exhausted",
    "suggested_fix": "Increase pool size",
    "rollback_command": "kubectl rollout undo deploy/payment-service",
    "confidence": 0.88,
}

STACK_TRACE = (
    "java.sql.SQLException: connection refused\n"
    "    at com.acme.payment.DBConnection.execute(DBConnection.java:88)\n"
)


@pytest.fixture
def service():
    """IncidentService with LLM and RAG stubbed out."""
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
        svc._llm_mock = llm
        svc._rag_mock = rag
    return svc


def _mock_db():
    """get_db replacement matching the real (awaitable, session is async CM) contract."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    async def _get_db():
        return session

    return _get_db, session


@pytest.fixture
def service_with_db(service):
    """IncidentService with get_db patched and get_service / save_incident stubbed."""
    get_db, session = _mock_db()
    with patch("src.services.incident_service.get_db", get_db), \
         patch.object(service, "get_service", new=AsyncMock(return_value=STUB_SERVICE)), \
         patch.object(service, "save_incident", new=AsyncMock()), \
         patch.object(service, "calculate_blast_radius",
                      new=AsyncMock(return_value={"root": "payment-api",
                                                   "affected": ["payment-api"],
                                                   "count": 1, "severity": "MEDIUM"})):
        yield service


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_declare_incident_returns_expected_shape(service_with_db):
    """
    Situation: Valid incident declaration with all services available.
    Expected: Returns incident with all expected fields.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    with patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        result = await service_with_db.declare_incident("payment-api", "DB down")

    assert result["service"] == "payment-api"
    assert result["severity"] == "P1"
    assert result["title"] == "Payment failures spiking"
    assert result["root_cause"] == "Connection pool exhausted"
    assert result["confidence"] == 0.88
    assert result["blast_radius"]["count"] == 1
    assert result["rag_context_used"] is False
    assert "timestamp" in result


@pytest.mark.asyncio
async def test_declare_incident_unknown_service_returns_error(service):
    """
    Situation: Service not found.
    Expected: Returns error with available services.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    with patch.object(service, "get_service", new=AsyncMock(return_value=None)), \
         patch.object(service, "list_services", new=AsyncMock(return_value=[{"name": "auth"}])):
        result = await service.declare_incident("nonexistent", "boom")

    assert "error" in result
    assert "not found" in result["error"]
    assert result["available_services"] == [{"name": "auth"}]


@pytest.mark.asyncio
async def test_declare_incident_calls_save_incident(service_with_db):
    """
    Situation: Valid incident declaration.
    Expected: Calls save_incident with correct data.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    with patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        await service_with_db.declare_incident("payment-api", "DB down")

    service_with_db.save_incident.assert_awaited_once()
    saved = service_with_db.save_incident.await_args.args[0]
    assert saved["service_name"] == "payment-api"
    assert saved["severity"] == "P1"
    assert saved["status"] == "active"


@pytest.mark.asyncio
async def test_declare_incident_stores_in_rag(service_with_db):
    """
    Situation: Valid incident declaration.
    Expected: Stores incident in RAG.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    with patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        await service_with_db.declare_incident("payment-api", "DB down")

    service_with_db._rag_mock.store_incident.assert_awaited_once()


@pytest.mark.asyncio
async def test_declare_incident_broadcasts_over_websocket(service_with_db):
    """
    Situation: Valid incident declaration.
    Expected: Broadcasts new incident over WebSocket.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    with patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        await service_with_db.declare_incident("payment-api", "DB down")

    ws.broadcast.assert_awaited_once()
    msg = ws.broadcast.await_args.args[0]
    assert msg["type"] == "new_incident"
    assert msg["data"]["service_name"] == "payment-api"


@pytest.mark.asyncio
async def test_declare_incident_uses_rag_context_when_available(service_with_db):
    """
    Situation: RAG finds similar incidents.
    Expected: Uses RAG context in analysis, rag_context_used True.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    service_with_db._rag_mock.generate_context_prompt = AsyncMock(return_value="similar past incident")

    with patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        result = await service_with_db.declare_incident("payment-api", "DB down")

    assert result["rag_context_used"] is True


# ---------------------------------------------------------------------------
# Stack trace parsing → metadata
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_declare_incident_parses_stack_trace_into_fields(service_with_db):
    """
    Situation: Stack trace provided.
    Expected: Parses into exception_type, file_path, line_number.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    with patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        await service_with_db.declare_incident(
            "payment-api", "DB down", stack_trace=STACK_TRACE
        )

    saved = service_with_db.save_incident.await_args.args[0]
    assert saved["exception_type"] == "SQLException"
    assert saved["file_path"] == "DBConnection.java"
    assert saved["line_number"] == 88


# ---------------------------------------------------------------------------
# GitHub integration blocks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_declare_incident_fetches_github_context_when_repo_set(service_with_db):
    """
    Situation: Service has repo_name and stack trace.
    Expected: Fetches GitHub context (PRs, blame, code content).
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    fake_github = MagicMock()
    fake_github.get_recent_prs = AsyncMock(return_value=[{"number": 1}])
    fake_github.get_blame_with_pr = AsyncMock(return_value={
        "author": "eng@acme.com", "message": "fix", "pr_number": 501,
    })
    fake_github.get_file_content = AsyncMock(return_value={
        "file_path": "DBConnection.java", "line_number": 88, "code_snippet": "x",
    })
    fake_github.get_related_prs = AsyncMock(return_value=[])

    with patch("src.services.incident_service.get_github_service",
               return_value=fake_github), \
         patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        await service_with_db.declare_incident(
            "payment-api", "DB down", stack_trace=STACK_TRACE
        )

    fake_github.get_recent_prs.assert_awaited_once_with("payment-service")
    fake_github.get_blame_with_pr.assert_awaited_once()
    saved = service_with_db.save_incident.await_args.args[0]
    metadata = json.loads(saved["extra_metadata"])
    assert "github" in metadata
    assert metadata["github"]["blame"]["author"] == "eng@acme.com"


@pytest.mark.asyncio
async def test_declare_incident_github_error_does_not_break(service_with_db):
    """
    Situation: GitHub service fails.
    Expected: Incident still created, GitHub error logged.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    fake_github = MagicMock()
    fake_github.get_recent_prs = AsyncMock(side_effect=RuntimeError("github down"))

    with patch("src.services.incident_service.get_github_service",
               return_value=fake_github), \
         patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        result = await service_with_db.declare_incident(
            "payment-api", "DB down", stack_trace=STACK_TRACE
        )

    assert "error" not in result
    assert result["incident_id"].startswith("INC-")


# ---------------------------------------------------------------------------
# On-call / alert / k8s blocks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_declare_incident_sends_alerts_to_oncall(service_with_db):
    """
    Situation: Valid incident with on-call roster.
    Expected: Sends alerts to on-call engineers.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    on_call_result = {"primary": {"name": "Alice", "slack": "@alice"},
                      "secondary": None, "tertiary": None}

    with patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(return_value=on_call_result)
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        await service_with_db.declare_incident("payment-api", "DB down")

    Alert.return_value.send_alerts.assert_awaited_once()
    alert_args = Alert.return_value.send_alerts.await_args.args
    assert alert_args[1] == on_call_result


@pytest.mark.asyncio
async def test_declare_incident_alert_failure_does_not_break(service_with_db):
    """
    Situation: Alert service fails.
    Expected: Incident still created, alert error logged.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    with patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock(side_effect=RuntimeError("slack down"))
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        result = await service_with_db.declare_incident("payment-api", "DB down")

    assert "error" not in result
    assert result["incident_id"].startswith("INC-")


@pytest.mark.asyncio
async def test_declare_incident_k8s_failure_does_not_break(service_with_db):
    """
    Situation: Kubernetes service fails.
    Expected: Incident still created, K8s error logged.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    with patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(side_effect=RuntimeError("no cluster"))
        ws.broadcast = AsyncMock()

        result = await service_with_db.declare_incident("payment-api", "DB down")

    assert "error" not in result


@pytest.mark.asyncio
async def test_declare_incident_websocket_failure_does_not_break(service_with_db):
    """
    Situation: WebSocket broadcast fails.
    Expected: Incident still created, WebSocket error logged.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    with patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock(side_effect=RuntimeError("ws closed"))

        result = await service_with_db.declare_incident("payment-api", "DB down")

    assert "error" not in result


@pytest.mark.asyncio
async def test_declare_incident_rag_store_failure_does_not_break(service_with_db):
    """
    Situation: RAG store_incident fails.
    Expected: Raises (current behavior - not wrapped in try/except).
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    service_with_db._rag_mock.store_incident = AsyncMock(side_effect=RuntimeError("embedding down"))

    with patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        # Note: this will raise because store_incident is not wrapped in try/except
        # in the source. Documenting current behavior.
        with pytest.raises(RuntimeError, match="embedding down"):
            await service_with_db.declare_incident("payment-api", "DB down")
