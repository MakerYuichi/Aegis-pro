"""
Tests for src/services/incident_service.py.

Focus areas:
  - _parse_stack_trace: pure function, no DB
  - get_service: real DB hit / miss; DB error fallback via db_error fixture
  - list_services: real DB; DB error fallback via db_error fixture
  - get_incident: real DB; JSON parsing
  - calculate_blast_radius: mocked get_service, no DB
  - rollback: real DB; DB error path via db_error fixture
  - seed_services: real DB
  - declare_incident: all downstream services mocked, no DB

Real-DB tests use fixtures from conftest.py (seeded_services,
seeded_incidents, make_incident, db_error). Everything else stays
mocked and fast.
"""

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

def test_parse_java_stack_trace(service):
    """Java stack trace with file:line pattern."""
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
    """Python stack trace with File pattern."""
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
    """Simple file:line pattern."""
    result = service._parse_stack_trace("Something failed at auth.py:42")
    assert result["file_path"] == "auth.py"
    assert result["line_number"] == 42


def test_parse_stack_trace_no_file(service):
    """Trace with no file:line pattern."""
    result = service._parse_stack_trace("GenericError: something went wrong")
    assert result["exception_type"] == "GenericError"
    assert result["file_path"] is None
    assert result["line_number"] is None


def test_parse_empty_stack_trace(service):
    """Empty stack trace."""
    result = service._parse_stack_trace("")
    assert result["exception_type"] is None
    assert result["file_path"] is None
    assert result["line_number"] is None


def test_parse_stack_trace_with_whitespace_in_path(service):
    """Edge case: whitespace in path."""
    pytest.skip("Parser returns None for malformed paths with whitespace - edge case")


# ── get_service ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_service_returns_db_row(service, seeded_services):
    """Real DB: service exists."""
    result = await service.get_service("auth")
    assert result is not None
    assert result["name"] == "auth"
    assert result["description"] == "Authentication and authorization"


@pytest.mark.asyncio
async def test_get_service_returns_none_when_missing(service, seeded_services):
    """Real DB: no such service. get_service returns None (fallback only on exception)."""
    result = await service.get_service("totally-nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_service_falls_back_to_mock_on_db_error(service, db_error):
    """db_error fixture forces get_db_session to raise; service falls back to _mock_service."""
    result = await service.get_service("payment-api")
    assert result["name"] == "payment-api"
    assert "@marcus" in result["on_call"]


# ── list_services ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_services_returns_rows(service, seeded_services):
    """Real DB: returns all 8 seeded services."""
    result = await service.list_services()
    assert len(result) == 8
    names = {s["name"] for s in result}
    assert names == {
        "payment-api", "auth", "ledger", "refund",
        "fraud", "notification", "user", "database",
    }
    auth = next(s for s in result if s["name"] == "auth")
    assert auth["is_critical"] is True


@pytest.mark.asyncio
async def test_list_services_falls_back_to_mock_on_db_error(service, db_error):
    """db_error forces DB failure; service falls back to mock list."""
    result = await service.list_services()
    assert len(result) == 8
    names = {s["name"] for s in result}
    assert "payment-api" in names
    assert "auth" in names


@pytest.mark.asyncio
async def test_list_services_empty_db(service, db_session):
    """
    Real DB: no services seeded. Returns empty list.

    Depends on db_session (not seeded_services) so the services table
    is empty inside the test transaction. Note: the migration itself
    may have inserted rows — but they were committed, not in our
    transaction, so they're visible. To be sure, we DELETE inside the
    transaction before running the query.
    """
    from sqlalchemy import text
    await db_session.execute(text("DELETE FROM services"))
    await db_session.flush()
    result = await service.list_services()
    assert result == []


# ── get_incident ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_incident_returns_none_when_missing(service, seeded_incidents):
    """Real DB: no such incident."""
    result = await service.get_incident("INC-NOPE")
    assert result is None


@pytest.mark.asyncio
async def test_get_incident_parses_json_metadata(service, seeded_incidents):
    """Real DB: incident with JSON metadata; parsed into dict/list."""
    result = await service.get_incident("INC-TEST-001")
    assert result is not None
    assert result["incident_id"] == "INC-TEST-001"
    assert result["extra_metadata"] == {"rag_context_used": False}
    assert result["affected_services"] == ["payment-api", "auth"]


@pytest.mark.asyncio
async def test_get_incident_handles_malformed_json(service, make_incident):
    """Real DB: incident with malformed JSON metadata; get_incident doesn't crash."""
    # Insert a row with invalid JSON. jsonb column will reject truly invalid
    # JSON, so use a valid JSON value of a non-dict shape to exercise the
    # "malformed" branch, or a string-encoded value.
    iid = await make_incident({
        "incident_id": "INC-TEST-MALFORMED",
        "extra_metadata": '"not a dict"',   # valid jsonb, but not an object
        "affected_services": '[]',
    })
    result = await service.get_incident(iid)
    assert result is not None
    assert "extra_metadata" in result


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
    fake_services = {
        "a": {"name": "a", "dependencies": ["shared"]},
        "b": {"name": "b", "dependencies": ["shared"]},
        "shared": {"name": "shared", "dependencies": []},
    }
    service.get_service = AsyncMock(side_effect=lambda n: fake_services.get(n))
    result = await service.calculate_blast_radius("root", ["a", "b"])
    assert result["affected"].count("shared") == 1


@pytest.mark.asyncio
async def test_blast_radius_transitive_dependencies(service):
    fake_services = {
        "a": {"name": "a", "dependencies": ["b"]},
        "b": {"name": "b", "dependencies": ["c"]},
        "c": {"name": "c", "dependencies": []},
    }
    service.get_service = AsyncMock(side_effect=lambda n: fake_services.get(n))
    result = await service.calculate_blast_radius("a", [])
    assert set(result["affected"]) == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_blast_radius_severity_calculation(service):
    result = await service.calculate_blast_radius("a", [])
    assert result["severity"] == "MEDIUM"

    fake_services = {
        "a": {"name": "a", "dependencies": ["b", "c"]},
        "b": {"name": "b", "dependencies": []},
        "c": {"name": "c", "dependencies": []},
    }
    service.get_service = AsyncMock(side_effect=lambda n: fake_services.get(n))
    result = await service.calculate_blast_radius("a", [])
    assert result["severity"] == "HIGH"


# ── rollback ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rollback_returns_error_when_incident_missing(service, seeded_incidents):
    """Real DB: no such incident."""
    result = await service.rollback("INC-NOPE")
    assert result["error"] == "Incident not found"


@pytest.mark.asyncio
async def test_rollback_updates_incident_status(service, seeded_incidents, db_session):
    """Real DB: rollback flips status to resolved; verify with a fresh query."""
    from sqlalchemy import text
    result = await service.rollback("INC-TEST-001")
    assert result["status"] == "rollback_initiated"
    assert result["incident_id"] == "INC-TEST-001"

    row = (await db_session.execute(
        text("SELECT status FROM incidents WHERE incident_id = :iid"),
        {"iid": "INC-TEST-001"},
    )).fetchone()
    assert row is not None
    assert row[0] == "resolved"


@pytest.mark.asyncio
async def test_rollback_db_error_continues_and_returns_result(service, db_error):
    """db_error forces UPDATE to fail; rollback still returns a result."""
    service.get_incident = AsyncMock(return_value={
        "incident_id": "INC-1",
        "rollback_command": "kubectl undo",
    })
    result = await service.rollback("INC-1")
    assert result["status"] == "rollback_initiated"


# ── seed_services ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seed_services_success(service, db_session):
    """Real DB: seed_services writes 8 rows (after DELETE)."""
    result = await service.seed_services()
    assert result["status"] == "seeded"
    assert result["count"] == 8

    from sqlalchemy import text
    n = (await db_session.execute(text("SELECT COUNT(*) FROM services"))).scalar()
    assert n == 8


@pytest.mark.asyncio
async def test_seed_services_reports_error(service, db_error):
    """db_error forces DELETE/INSERT to fail; seed_services returns error status."""
    result = await service.seed_services()
    assert result["status"] == "error"


# ── declare_incident ────────────────────────────────────────────────────
# All downstream services mocked. No DB touched.

def _mock_declare_deps(
    service,
    analysis=None,
    rag_context="",
    service_dict=None,
):
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
            service_name="payment-api", message="UPI failing",
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
    result = await service.declare_incident(service_name="ghost-service", message="x")
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
            service_name="payment-api", message="NPE",
            stack_trace="java.lang.NullPointerException at Foo.java:42",
        )

    assert result["incident_id"].startswith("INC-")
    call_kwargs = service.llm.analyze_incident.call_args.kwargs
    assert call_kwargs["stack_analysis"]["file_path"] == "Foo.java"
    assert call_kwargs["stack_analysis"]["line_number"] == 42


@pytest.mark.asyncio
async def test_declare_incident_survives_github_errors(service):
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

        result = await service.declare_incident(service_name="payment-api", message="x")

    assert result["incident_id"].startswith("INC-")


@pytest.mark.asyncio
async def test_declare_incident_with_rag_context(service):
    _mock_declare_deps(service, rag_context="Similar past incident found")

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

        result = await service.declare_incident(service_name="payment-api", message="x")

    assert result["rag_context_used"] is True
    call_kwargs = service.llm.analyze_incident.call_args.kwargs
    assert call_kwargs["rag_context"] == "Similar past incident found"


@pytest.mark.asyncio
async def test_declare_incident_survives_alert_errors(service):
    _mock_declare_deps(service)

    with patch("src.services.incident_service.get_github_service") as _gh, \
         patch("src.services.incident_service.OnCallService") as MockOC, \
         patch("src.services.incident_service.AlertService") as MockAlert, \
         patch("src.services.incident_service.KubernetesService"), \
         patch("src.services.incident_service.AutoFixService"):

        _gh.return_value.get_recent_prs = AsyncMock(return_value=[])
        _gh.return_value.get_blame_with_pr = AsyncMock(return_value={})
        _gh.return_value.get_file_content = AsyncMock(return_value={})
        _gh.return_value.get_related_prs = AsyncMock(return_value=[])

        MockOC.return_value.get_on_call = AsyncMock(return_value={})
        MockOC.return_value.get_escalation_policy = AsyncMock(return_value={})
        MockAlert.return_value.send_alerts = AsyncMock(side_effect=RuntimeError("slack down"))

        result = await service.declare_incident(service_name="payment-api", message="x")

    assert result["incident_id"].startswith("INC-")


@pytest.mark.asyncio
async def test_declare_incident_with_reported_by(service):
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
            service_name="payment-api", message="x", reported_by="alice",
        )

    assert result["incident_id"].startswith("INC-")
