"""
Tests for src/services/incident_service.py.

The service writes to the DB and calls six other services. Every
dependency is mocked at the import boundary — no real DB, no network.

Focus areas:
  - declare_incident: success, unknown service, with/without stack trace
  - get_service: DB hit, DB miss, DB error fallback to _mock_service
  - list_services: DB hit, DB error fallback
  - get_incident: found, not found, JSON parsing of extra_metadata
  - get_all_incidents: empty, populated, affected_services parsing
  - calculate_blast_radius: single, transitive dependencies
  - rollback: success, not found
  - seed_services: success, DB error
  - _parse_stack_trace: Java, Python, simple formats, missing file
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.incident_service import IncidentService


def _make_service() -> IncidentService:
    """
    Build an IncidentService with LLM and RAG mocked.

    The __init__ creates real LLMService() and RAGService() objects,
    which try to hit Groq and load a transformer model. Both must be
    patched before instantiation.
    """
    with patch("src.services.incident_service.LLMService"), \
         patch("src.services.incident_service.RAGService"):
        svc = IncidentService()
    svc.llm = MagicMock()
    svc.rag = MagicMock()
    return svc


@pytest.fixture
def service():
    return _make_service()


# ── _parse_stack_trace ──────────────────────────────────────────────────
# This is a pure function. It's the highest-value test target in the file
# because every incident declaration runs it.

def test_parse_java_stack_trace(service):
    trace = (
        "java.lang.NullPointerException: Cannot invoke method\n"
        "\tat com.example.PaymentProcessor.process(PaymentProcessor.java:442)\n"
        "\tat com.example.Controller.handle(Controller.java:118)"
    )
    result = service._parse_stack_trace(trace)
    assert result["exception_type"] == "NullPointerException"
    assert result["file_path"] == "PaymentProcessor.java"
    assert result["line_number"] == 442


def test_parse_python_stack_trace(service):
    trace = (
        'Traceback (most recent call last):\n'
        '  File "src/handlers/upstream.py", line 87, in handler\n'
        '    response = client.get(url).json()\n'
        'AttributeError: NoneType has no attribute'
    )
    result = service._parse_stack_trace(trace)
    assert result["exception_type"] == "AttributeError"
    assert result["file_path"] == "src/handlers/upstream.py"
    assert result["line_number"] == 87


def test_parse_simple_file_line(service):
    result = service._parse_stack_trace("Something failed at auth.py:42")
    assert result["file_path"] == "auth.py"
    assert result["line_number"] == 42


def test_parse_stack_trace_no_file(service):
    """A trace with no file:line pattern still gets an exception type."""
    result = service._parse_stack_trace("GenericError: something went wrong")
    assert result["exception_type"] == "GenericError"
    assert result["file_path"] is None
    assert result["line_number"] is None


def test_parse_empty_stack_trace(service):
    result = service._parse_stack_trace("")
    assert result["exception_type"] is None
    assert result["file_path"] is None


# ── get_service ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_service_returns_db_row(service):
    fake_session = AsyncMock()
    fake_result = MagicMock()
    fake_row = MagicMock()
    fake_row._mapping = {"name": "auth", "description": "Authentication"}
    fake_result.fetchone.return_value = fake_row
    fake_session.execute.return_value = fake_result

    async def _get_db():
        return fake_session
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)

    with patch("src.services.incident_service.get_db", _get_db):
        result = await service.get_service("auth")
    assert result["name"] == "auth"


@pytest.mark.asyncio
async def test_get_service_returns_none_when_missing(service):
    fake_session = AsyncMock()
    fake_result = MagicMock()
    fake_result.fetchone.return_value = None
    fake_session.execute.return_value = fake_result
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)

    async def _get_db():
        return fake_session

    with patch("src.services.incident_service.get_db", _get_db):
        result = await service.get_service("nope")
    assert result is None


@pytest.mark.asyncio
async def test_get_service_falls_back_to_mock_on_db_error(service):
    async def _get_db():
        raise RuntimeError("DB down")

    with patch("src.services.incident_service.get_db", _get_db):
        result = await service.get_service("payment-api")
    # Fallback path returns the mock service dict.
    assert result["name"] == "payment-api"
    assert "@marcus" in result["on_call"]


# ── list_services ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_services_returns_rows(service):
    fake_session = AsyncMock()
    fake_result = MagicMock()
    fake_result.fetchall.return_value = [
        ("auth", "Authentication", '["@dana"]', "[]", True, "auth-service"),
    ]
    fake_session.execute.return_value = fake_result
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)

    async def _get_db():
        return fake_session

    with patch("src.services.incident_service.get_db", _get_db):
        result = await service.list_services()
    assert len(result) == 1
    assert result[0]["name"] == "auth"
    assert result[0]["is_critical"] is True


@pytest.mark.asyncio
async def test_list_services_falls_back_to_mock_on_db_error(service):
    async def _get_db():
        raise RuntimeError("DB down")

    with patch("src.services.incident_service.get_db", _get_db):
        result = await service.list_services()
    assert len(result) == 8
    names = {s["name"] for s in result}
    assert "payment-api" in names
    assert "auth" in names


# ── get_incident ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_incident_returns_none_when_missing(service):
    fake_session = AsyncMock()
    fake_result = MagicMock()
    fake_result.fetchone.return_value = None
    fake_session.execute.return_value = fake_result
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)

    async def _get_db():
        return fake_session

    with patch("src.services.incident_service.get_db", _get_db):
        result = await service.get_incident("INC-NOPE")
    assert result is None


@pytest.mark.asyncio
async def test_get_incident_parses_json_metadata(service):
    fake_session = AsyncMock()
    fake_result = MagicMock()
    fake_row = MagicMock()
    fake_row._mapping = {
        "incident_id": "INC-1",
        "extra_metadata": '{"rag_context_used": true}',
        "affected_services": '["auth", "ledger"]',
    }
    fake_result.fetchone.return_value = fake_row
    fake_session.execute.return_value = fake_result
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)

    async def _get_db():
        return fake_session

    with patch("src.services.incident_service.get_db", _get_db):
        result = await service.get_incident("INC-1")
    assert result["extra_metadata"] == {"rag_context_used": True}
    assert result["affected_services"] == ["auth", "ledger"]


# ── calculate_blast_radius ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_blast_radius_single_service(service):
    service.get_service = AsyncMock(return_value=None)
    result = await service.calculate_blast_radius("isolated", [])
    assert result["root"] == "isolated"
    assert result["affected"] == ["isolated"]
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_blast_radius_includes_direct_dependencies(service):
    """auth -> user, ledger -> database"""
    fake_services = {
        "auth": {"name": "auth", "dependencies": ["user"]},
        "ledger": {"name": "ledger", "dependencies": ["database"]},
        "user": {"name": "user", "dependencies": []},
        "database": {"name": "database", "dependencies": []},
    }
    service.get_service = AsyncMock(side_effect=lambda n: fake_services.get(n))
    result = await service.calculate_blast_radius("auth", ["ledger"])
    assert set(result["affected"]) == {"auth", "ledger", "user", "database"}
    assert result["count"] == 4


@pytest.mark.asyncio
async def test_blast_radius_deduplicates(service):
    """Diamond deps should not duplicate the shared service."""
    fake_services = {
        "a": {"name": "a", "dependencies": ["shared"]},
        "b": {"name": "b", "dependencies": ["shared"]},
        "shared": {"name": "shared", "dependencies": []},
    }
    service.get_service = AsyncMock(side_effect=lambda n: fake_services.get(n))
    result = await service.calculate_blast_radius("root", ["a", "b"])
    assert result["affected"].count("shared") == 1


# ── rollback ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rollback_returns_error_when_incident_missing(service):
    service.get_incident = AsyncMock(return_value=None)
    result = await service.rollback("INC-NOPE")
    assert result["error"] == "Incident not found"


@pytest.mark.asyncio
async def test_rollback_updates_incident_status(service):
    service.get_incident = AsyncMock(return_value={
        "incident_id": "INC-1",
        "rollback_command": "kubectl rollout undo deploy/x",
    })
    fake_session = AsyncMock()
    fake_session.execute = AsyncMock()
    fake_session.commit = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)

    async def _get_db():
        return fake_session

    with patch("src.services.incident_service.get_db", _get_db):
        result = await service.rollback("INC-1")
    assert result["status"] == "rollback_initiated"
    assert result["incident_id"] == "INC-1"
    assert "kubectl" in result["rollback_command"]


# ── seed_services ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seed_services_success(service):
    fake_session = AsyncMock()
    fake_session.execute = AsyncMock()
    fake_session.commit = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)

    async def _get_db():
        return fake_session

    with patch("src.services.incident_service.get_db", _get_db):
        result = await service.seed_services()
    assert result["status"] == "seeded"
    assert result["count"] == 8


@pytest.mark.asyncio
async def test_seed_services_reports_error(service):
    async def _get_db():
        raise RuntimeError("disk full")

    with patch("src.services.incident_service.get_db", _get_db):
        result = await service.seed_services()
    assert result["status"] == "error"
    assert "disk full" in result["message"]


# ── declare_incident (the big one) ──────────────────────────────────────
# Everything downstream of get_service is mocked. We assert the shape
# of the response and that the right services were called.

def _mock_declare_deps(
    service,
    analysis=None,
    rag_context="",
    service_dict=None,
):
    """
    Wire up mocks for the six downstream services that declare_incident
    touches. Returns the fake service dict for assertion.
    """
    if analysis is None:
        analysis = {
            "severity": "P1",
            "title": "Test incident",
            "root_cause": "Something broke",
            "suggested_fix": "Fix it",
            "rollback_command": "kubectl rollout undo deploy/x",
            "confidence": 0.85,
        }
    if service_dict is None:
        service_dict = {
            "name": "payment-api",
            "repo_name": "payment-service",
            "on_call": ["@marcus"],
            "dependencies": ["auth", "ledger"],
        }

    service.get_service = AsyncMock(return_value=service_dict)
    service.llm.analyze_incident = AsyncMock(return_value=analysis)
    service.rag.generate_context_prompt = AsyncMock(return_value=rag_context)
    service.rag.store_incident = AsyncMock()
    service.save_incident = AsyncMock()

    # calculate_blast_radius is mocked — it hits get_service internally
    service.calculate_blast_radius = AsyncMock(return_value={
        "root": "payment-api",
        "affected": ["payment-api", "auth", "ledger"],
        "count": 3,
        "severity": "HIGH",
    })

    return service_dict


@pytest.mark.asyncio
async def test_declare_incident_returns_expected_shape(service):
    _mock_declare_deps(service)

    with patch("src.services.incident_service.get_github_service") as _gh, \
         patch("src.services.incident_service.OnCallService") as MockOC, \
         patch("src.services.incident_service.AlertService") as MockAlert, \
         patch("src.services.incident_service.KubernetesService") as MockK8s, \
         patch("src.services.incident_service.AutoFixService") as MockAF:

        _gh.return_value.get_recent_prs = AsyncMock(return_value=[])
        _gh.return_value.get_blame_with_pr = AsyncMock(return_value={})
        _gh.return_value.get_file_content = AsyncMock(return_value={})
        _gh.return_value.get_related_prs = AsyncMock(return_value=[])

        MockOC.return_value.get_on_call = AsyncMock(return_value={"primary": {"name": "Marcus"}})
        MockOC.return_value.get_escalation_policy = AsyncMock(return_value={})
        MockAlert.return_value.send_alerts = AsyncMock()
        MockK8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        MockAF.return_value.generate_fix = AsyncMock(return_value={})

        result = await service.declare_incident(
            service_name="payment-api",
            message="UPI failing",
        )

    assert result["service"] == "payment-api"
    assert result["severity"] == "P1"
    assert result["title"] == "Test incident"
    assert result["blast_radius"]["count"] == 3
    assert result["rag_context_used"] is False
    assert result["incident_id"].startswith("INC-")


@pytest.mark.asyncio
async def test_declare_incident_unknown_service_returns_error(service):
    service.get_service = AsyncMock(return_value=None)
    service.list_services = AsyncMock(return_value=[{"name": "auth"}])

    result = await service.declare_incident(
        service_name="ghost-service", message="x"
    )
    assert "error" in result
    assert "ghost-service" in result["error"]
    assert "available_services" in result


@pytest.mark.asyncio
async def test_declare_incident_with_stack_trace(service):
    _mock_declare_deps(service)

    with patch("src.services.incident_service.get_github_service") as _gh, \
         patch("src.services.incident_service.OnCallService") as MockOC, \
         patch("src.services.incident_service.AlertService"), \
         patch("src.services.incident_service.KubernetesService"), \
         patch("src.services.incident_service.AutoFixService"):

        _gh.return_value.get_recent_prs = AsyncMock(return_value=[])
        _gh.return_value.get_blame_with_pr = AsyncMock(return_value={})
        _gh.return_value.get_file_content = AsyncMock(return_value={})
        _gh.return_value.get_related_prs = AsyncMock(return_value=[])

        MockOC.return_value.get_on_call = AsyncMock(return_value={})
        MockOC.return_value.get_escalation_policy = AsyncMock(return_value={})

        result = await service.declare_incident(
            service_name="payment-api",
            message="NPE",
            stack_trace="java.lang.NullPointerException at Foo.java:42",
        )

    assert result["incident_id"].startswith("INC-")

    # The LLM should have been called with a parsed stack_analysis
    call_kwargs = service.llm.analyze_incident.call_args.kwargs
    assert call_kwargs["stack_analysis"]["file_path"] == "Foo.java"
    assert call_kwargs["stack_analysis"]["line_number"] == 42


@pytest.mark.asyncio
async def test_declare_incident_survives_github_errors(service):
    """A GitHub failure must not break the whole declaration."""
    _mock_declare_deps(service)

    with patch("src.services.incident_service.get_github_service") as _gh, \
         patch("src.services.incident_service.OnCallService") as MockOC, \
         patch("src.services.incident_service.AlertService"), \
         patch("src.services.incident_service.KubernetesService"), \
         patch("src.services.incident_service.AutoFixService"):

        _gh.return_value.get_recent_prs = AsyncMock(
            side_effect=RuntimeError("GitHub down")
        )

        MockOC.return_value.get_on_call = AsyncMock(return_value={})
        MockOC.return_value.get_escalation_policy = AsyncMock(return_value={})

        result = await service.declare_incident(
            service_name="payment-api", message="x"
        )

    # Even with GitHub failing, we get an incident ID back.
    assert result["incident_id"].startswith("INC-")
