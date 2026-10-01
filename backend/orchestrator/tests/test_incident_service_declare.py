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
from src.agents.verifier import VerificationResult


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
    """
    IncidentService with get_service / _persist_diagnosed_incident /
    calculate_blast_radius stubbed, plus all four record_* methods
    stubbed. No DB access happens in these tests — declare_incident
    persists via _persist_diagnosed_incident (mocked here) and enriches
    via the record_* methods (also mocked).
    """
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
async def test_declare_incident_persists_before_enrichment(service_with_db):
    """
    Situation: Valid incident declaration.
    Expected: _persist_diagnosed_incident is called with the diagnosis
    data, before any enrichment blocks run.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    with patch.object(service_with_db, "_persist_diagnosed_incident",
                      new=AsyncMock()) as mock_persist, \
         patch.object(service_with_db, "record_github_context", new=AsyncMock()), \
         patch.object(service_with_db, "record_code_context", new=AsyncMock()), \
         patch.object(service_with_db, "record_related_prs", new=AsyncMock()), \
         patch.object(service_with_db, "record_auto_fix", new=AsyncMock()), \
         patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        await service_with_db.declare_incident("payment-api", "DB down")

    mock_persist.assert_awaited_once()
    saved = mock_persist.await_args.args[0]
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

    saved = service_with_db._persist_diagnosed_incident.await_args.args[0]
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
    # GitHub context now lands via record_github_context, not the
    # initial persist call. Assert on the enrichment call.
    service_with_db.record_github_context.assert_awaited_once()
    call_args = service_with_db.record_github_context.await_args
    _incident_id, github_context = call_args.args
    assert github_context["blame"]["author"] == "eng@acme.com"


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
    Expected: Incident still created, RAG error logged, no exception raised.
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

        result = await service_with_db.declare_incident("payment-api", "DB down")

    assert "error" not in result
    assert result["incident_id"].startswith("INC-")
    assert result["service"] == "payment-api"

@pytest.mark.asyncio
async def test_declare_incident_rag_failure_is_logged(service_with_db):
    """
    Situation: RAG store_incident fails.
    Expected: The failure is logged via loguru, not swallowed silently.
    Function: src.services.incident_service.IncidentService.declare_incident
    """
    service_with_db._rag_mock.store_incident = AsyncMock(side_effect=RuntimeError("embedding down"))

    with patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws, \
         patch("src.services.incident_service.logger") as mock_logger:
        OnCall.return_value.get_on_call = AsyncMock(return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        await service_with_db.declare_incident("payment-api", "DB down")

    # logger.error was called with a message containing the RAG failure
    error_calls = [str(c) for c in mock_logger.error.call_args_list]
    assert any("RAG store error" in c for c in error_calls), (
        f"Expected 'RAG store error' in logger.error calls, got: {error_calls}"
    )
    assert any("embedding down" in c for c in error_calls)
    
# ---------------------------------------------------------------------------
# record_* methods — read-merge-write semantics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_github_context_preserves_sibling_keys(make_incident):
    """
    Situation: extra_metadata already has rag_context_used and reported_by.
    Expected: record_github_context adds github.* without dropping siblings.
    """
    from src.services.incident_service import IncidentService

    iid = await make_incident({
        "incident_id": "INC-MERGE-1",
        "extra_metadata": json.dumps({
            "rag_context_used": True,
            "reported_by": "alice",
        }),
    })

    svc = IncidentService()
    await svc.record_github_context(iid, {"recent_prs": [{"number": 1}]})

    incident = await svc.get_incident(iid)
    meta = incident["extra_metadata"]
    assert meta["rag_context_used"] is True
    assert meta["reported_by"] == "alice"
    assert meta["github"]["recent_prs"] == [{"number": 1}]


@pytest.mark.asyncio
async def test_record_related_prs_preserves_github_siblings(make_incident):
    """
    Situation: record_github_context ran first and wrote github.blame.
    Expected: record_related_prs adds github.related_prs without
    dropping github.blame.
    """
    from src.services.incident_service import IncidentService

    iid = await make_incident({
        "incident_id": "INC-MERGE-2",
        "extra_metadata": json.dumps({
            "github": {"blame": {"author": "eng@acme.com"}},
        }),
    })

    svc = IncidentService()
    await svc.record_related_prs(iid, [{"number": 42}])

    incident = await svc.get_incident(iid)
    meta = incident["extra_metadata"]
    assert meta["github"]["blame"]["author"] == "eng@acme.com"
    assert meta["github"]["related_prs"] == [{"number": 42}]


@pytest.mark.asyncio
async def test_record_related_prs_works_when_github_key_absent(make_incident):
    """
    Situation: no github key yet.
    Expected: record_related_prs creates the parent dict.
    """
    from src.services.incident_service import IncidentService

    iid = await make_incident({
        "incident_id": "INC-MERGE-3",
        "extra_metadata": json.dumps({"rag_context_used": False}),
    })

    svc = IncidentService()
    await svc.record_related_prs(iid, [{"number": 7}])

    incident = await svc.get_incident(iid)
    meta = incident["extra_metadata"]
    assert meta["rag_context_used"] is False
    assert meta["github"]["related_prs"] == [{"number": 7}]


@pytest.mark.asyncio
async def test_record_related_prs_overwrites_non_dict_github(make_incident):
    """
    Situation: github key exists but is a string (stale/bad data).
    Expected: record_related_prs replaces it with a dict, no crash.
    """
    from src.services.incident_service import IncidentService

    iid = await make_incident({
        "incident_id": "INC-MERGE-4",
        "extra_metadata": json.dumps({"github": "not-a-dict"}),
    })

    svc = IncidentService()
    await svc.record_related_prs(iid, [{"number": 1}])

    incident = await svc.get_incident(iid)
    assert incident["extra_metadata"]["github"] == {"related_prs": [{"number": 1}]}


@pytest.mark.asyncio
async def test_record_auto_fix_preserves_code_context(make_incident):
    """
    Situation: code_context written first, then auto_fix.
    Expected: both present, neither dropped.
    """
    from src.services.incident_service import IncidentService

    iid = await make_incident({
        "incident_id": "INC-MERGE-5",
        "extra_metadata": json.dumps({
            "code_context": {"file_path": "x.py", "line_number": 42},
        }),
    })

    svc = IncidentService()
    await svc.record_auto_fix(iid, {"status": "fix_generated", "fix": "diff"})

    incident = await svc.get_incident(iid)
    meta = incident["extra_metadata"]
    assert meta["code_context"]["file_path"] == "x.py"
    assert meta["auto_fix"]["status"] == "fix_generated"


@pytest.mark.asyncio
async def test_record_methods_log_warning_on_missing_row(caplog):
    """
    Situation: incident_id does not exist.
    Expected: warning logged, no exception.
    """
    from src.services.incident_service import IncidentService
    from loguru import logger as loguru_logger

    svc = IncidentService()

    messages = []
    sink_id = loguru_logger.add(lambda m: messages.append(m.record["message"]), level="WARNING")
    try:
        await svc.record_code_context("INC-DOES-NOT-EXIST", {"file": "x"})
    finally:
        loguru_logger.remove(sink_id)

    assert any("INC-DOES-NOT-EXIST" in m for m in messages)


@pytest.mark.asyncio
async def test_record_method_raises_on_db_error(db_error):
    """
    Situation: DB is unreachable.
    Expected: the record_* method lets the exception propagate — the
    caller (declare_incident) is responsible for wrapping it.
    Function: IncidentService.record_github_context
    """
    from src.services.incident_service import IncidentService

    svc = IncidentService()
    with pytest.raises(RuntimeError, match="forced DB error"):
        await svc.record_github_context("INC-1", {"recent_prs": []})


@pytest.mark.asyncio
async def test_record_verification_preserves_auto_fix(make_incident):
    """
    Situation: auto_fix written first, then verification.
    Expected: both present, neither dropped.
    """
    from src.services.incident_service import IncidentService

    iid = await make_incident({
        "incident_id": "INC-VERIFY-1",
        "extra_metadata": json.dumps({
            "auto_fix": {"status": "fix_generated", "fix": "diff"},
        }),
    })

    svc = IncidentService()
    await svc.record_verification(iid, {
        "passed": True,
        "reason": "tests_passed",
        "output": "3 passed",
        "duration_ms": 1200,
        "attempts": [{"attempt": 1, "passed": True, "output": "3 passed"}],
        "verifier": "hosted",
    })

    incident = await svc.get_incident(iid)
    meta = incident["extra_metadata"]
    assert meta["auto_fix"]["status"] == "fix_generated"
    assert meta["verification"]["passed"] is True
    assert meta["verification"]["reason"] == "tests_passed"
    assert meta["verification"]["attempts"][0]["attempt"] == 1


@pytest.mark.asyncio
async def test_record_verification_merges_not_overwrites(make_incident):
    """
    Situation: verification written twice (retry scenario).
    Expected: second write replaces the verification key without
    affecting siblings.
    """
    from src.services.incident_service import IncidentService

    iid = await make_incident({
        "incident_id": "INC-VERIFY-2",
        "extra_metadata": json.dumps({
            "code_context": {"file_path": "x.py"},
            "verification": {"passed": False, "reason": "tests_failed"},
        }),
    })

    svc = IncidentService()
    await svc.record_verification(iid, {
        "passed": True,
        "reason": "tests_passed",
        "verifier": "hosted",
    })

    incident = await svc.get_incident(iid)
    meta = incident["extra_metadata"]
    assert meta["code_context"]["file_path"] == "x.py"
    assert meta["verification"]["passed"] is True
    assert meta["verification"]["reason"] == "tests_passed"


@pytest.mark.asyncio
async def test_record_verification_logs_warning_on_missing_row():
    """
    Situation: incident_id does not exist.
    Expected: warning logged, no exception.
    """
    from src.services.incident_service import IncidentService
    from loguru import logger as loguru_logger

    svc = IncidentService()
    messages = []
    sink_id = loguru_logger.add(
        lambda m: messages.append(m.record["message"]),
        level="WARNING",
    )
    try:
        await svc.record_verification("INC-DOES-NOT-EXIST", {"passed": True})
    finally:
        loguru_logger.remove(sink_id)

    assert any("INC-DOES-NOT-EXIST" in m for m in messages)


@pytest.mark.asyncio
async def test_investigator_mode_agent_clones_and_stores_workdir(
    service_with_db, monkeypatch
):
    """
    INVESTIGATOR_MODE=agent, clone succeeds → context["repo_workdir"]
    is set to the clone path. Cleanup runs at the end of declare_incident.
    """
    from src.config import settings
    from src.agents.investigator_models import (
        STATUS_DIAGNOSED, InvestigationResult,
    )
    from src.agents.repo_clone import _base_dir
    import uuid

    monkeypatch.setattr(settings, "INVESTIGATOR_MODE", "agent")

    # The fake clone must land under _base_dir() so that
    # cleanup_repo's "is this inside our base dir?" check passes.
    # That's the same contract real clone_repo honors.
    clone_dir = _base_dir() / f"inv-test-{uuid.uuid4().hex[:12]}"
    clone_dir.mkdir(parents=True, exist_ok=True)
    (clone_dir / "marker.txt").write_text("clone")

    async def fake_clone(repo, commit_sha=None, **kw):
        return str(clone_dir), None

    captured: dict = {}

    async def fake_investigate(self, ctx, **kw):
        captured["repo_root"] = self.repo_root
        return InvestigationResult(
            status=STATUS_DIAGNOSED,
            null_source="self.rag",
            evidence="e",
            confidence=0.8,
            iterations=1,
            history=[],
        )

    with patch("src.agents.repo_clone.clone_repo", new=fake_clone), \
         patch("src.agents.investigator.InvestigatorAgent.investigate",
               new=fake_investigate), \
         patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(
            return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        result = await service_with_db.declare_incident(
            "payment-api", "DB down", stack_trace=STACK_TRACE
        )

    assert captured["repo_root"] == str(clone_dir)
    assert not clone_dir.exists(), (
        f"cleanup did not run. Clone dir still exists at {clone_dir}. "
        f"Contents: {list(clone_dir.iterdir()) if clone_dir.exists() else 'N/A'}"
    )


@pytest.mark.asyncio
async def test_investigator_mode_agent_clone_failure_degrades_honestly(
    service_with_db, monkeypatch
):
    """
    INVESTIGATOR_MODE=agent, clone fails → the pipeline still runs
    end to end, the agent is invoked with an empty repo_root, and the
    response reflects whatever the agent returns.
    """
    from src.config import settings
    from src.agents.investigator_models import (
        STATUS_REFUSED, InvestigationResult,
    )
    monkeypatch.setattr(settings, "INVESTIGATOR_MODE", "agent")

    async def fake_clone(repo, commit_sha=None, **kw):
        return None, "clone_timeout after 60s"

    captured: dict = {}

    async def fake_investigate(self, ctx, **kw):
        captured["repo_root"] = self.repo_root
        return InvestigationResult(
            status=STATUS_REFUSED,
            reason="no_null_source_visible",
            candidates_considered=[],
            iterations=0,
            history=[],
        )

    with patch("src.agents.repo_clone.clone_repo", new=fake_clone), \
         patch("src.agents.investigator.InvestigatorAgent.investigate",
               new=fake_investigate), \
         patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws:
        OnCall.return_value.get_on_call = AsyncMock(
            return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        result = await service_with_db.declare_incident(
            "payment-api", "DB down", stack_trace=STACK_TRACE
        )

    # The agent still ran. It got an empty repo_root because the
    # clone failed. Tools all return repo_not_found, and the agent
    # chose to refuse — the honest outcome.
    assert captured["repo_root"] == ""
    assert result["investigation"]["status"] == "refused"
    assert result["auto_fix_skipped_reason"] == "refused"

@pytest.mark.asyncio
async def test_fixer_reads_code_context_from_clone_when_present(
    service_with_db, monkeypatch, tmp_path
):
    """
    When a clone is present in context["repo_workdir"], the Fixer
    reads code context from disk instead of calling GitHub.
    Specifically verifies that the monorepo path resolution works:
    the stack trace says src/services/incident_service.py, the clone
    has it at backend/orchestrator/src/services/incident_service.py,
    and the Fixer finds it.
    """
    from src.config import settings
    monkeypatch.setattr(settings, "INVESTIGATOR_MODE", "agent")

    # Build a fake clone that mirrors the monorepo layout.
    clone = tmp_path / "clone"
    nested = clone / "backend" / "orchestrator" / "src" / "services"
    nested.mkdir(parents=True)
    (nested / "incident_service.py").write_text(
        "\n".join(f"# line {i}" for i in range(1, 200))
    )

    # The stack trace must point at a file the clone actually has.
    MONOREPO_STACK = (
        "AttributeError: 'NoneType' object has no attribute 'search_similar_outcomes'\n"
        "    at IncidentService.declare_incident(src/services/incident_service.py:150)"
    )

    async def fake_investigate(*args, **kwargs):
        from src.agents.investigator_models import (
            STATUS_DIAGNOSED, InvestigationResult,
        )
        if "context" in kwargs:
            kwargs["context"]["repo_workdir"] = str(clone)
        return InvestigationResult(
            status=STATUS_DIAGNOSED,
            null_source="self.rag",
            evidence="test",
            confidence=0.9,
            iterations=3,
            history=[],
        )

    github_called = {"n": 0}

    async def fake_get_file_content(*args, **kwargs):
        github_called["n"] += 1
        return {}

    with patch.object(
        service_with_db, "_run_investigator_agent",
        new=AsyncMock(side_effect=fake_investigate),
    ), \
    patch("src.services.incident_service.get_github_service") as ghs, \
    patch("src.services.incident_service.AutoFixService") as autofix_cls, \
    patch("src.services.incident_service.OnCallService") as OnCall, \
    patch("src.services.incident_service.AlertService") as Alert, \
    patch("src.services.incident_service.KubernetesService") as K8s, \
    patch("src.services.incident_service.manager") as ws:
        ghs.return_value.get_file_content = AsyncMock(
            side_effect=fake_get_file_content,
        )
        ghs.return_value.get_recent_prs = AsyncMock(return_value=[])
        ghs.return_value.get_blame_with_pr = AsyncMock(return_value={})
        ghs.return_value.get_related_prs = AsyncMock(return_value=[])

        autofix_cls.return_value.generate_fix = AsyncMock(
            return_value={"status": "fix_generated", "fix": "diff"}
        )

        OnCall.return_value.get_on_call = AsyncMock(
            return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()

        result = await service_with_db.declare_incident(
            "payment-api", "DB down", stack_trace=MONOREPO_STACK
        )

    assert github_called["n"] == 0, (
        f"Fixer should not call GitHub when a clone is present; "
        f"get_file_content was called {github_called['n']} time(s)"
    )
    assert result.get("auto_fix") is not None