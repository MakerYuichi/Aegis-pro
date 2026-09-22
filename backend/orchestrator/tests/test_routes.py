"""
Tests for src/api/routes.py.

Every endpoint gets at least one test. Services are mocked at the
import boundary — no DB, no LLM, no network calls.

Two categories:

  Public endpoints — no token required
    GET  /ping
    GET  /incident/{id}
    GET  /incidents
    GET  /services
    GET  /fixes/pending
    GET  /oncall
    GET  /oncall/alert/history

  Auth-required endpoints — Depends(require_auth)
    POST /incident/declare
    POST /incident/rollback
    POST /incident/{id}/approve
    POST /incident/{id}/reject
    POST /services
    DELETE /services/{name}
    POST /services/seed
    POST /fixes/{id}/approve
    POST /fixes/{id}/reject
    POST /oncall/members
    DELETE /oncall/members/{id}
    POST /oncall/alert
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock

from src.api.routes import router as routes_router


def _make_app() -> FastAPI:
    """Build a minimal app with a fake incident_service on app.state."""
    app = FastAPI()
    app.state.incident_service = MagicMock()
    app.include_router(routes_router, prefix="/api/v1")
    return app


@pytest.fixture
def client_authed():
    """
    Client with the require_auth dependency overridden.

    FastAPI captures Depends(require_auth) at route registration time,
    so patching the module attribute after the fact has no effect. The
    correct approach is app.dependency_overrides.
    """
    from src.api.routes import require_auth

    async def _fake_require_auth():
        return {"sub": "auth0|test-user", "email": "test@example.com"}

    app = _make_app()
    app.dependency_overrides[require_auth] = _fake_require_auth
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_public():
    """Client without patching auth — used only for public endpoints."""
    app = _make_app()
    yield TestClient(app)


# ── Public endpoints ────────────────────────────────────────────────────

def test_ping_returns_pong(client_public):
    """
    Situation: Ping endpoint called.
    Expected: Returns pong with alive status.
    Function: src.api.routes.ping
    """
    r = client_public.get("/api/v1/ping")
    assert r.status_code == 200
    body = r.json()
    assert body["message"] == "pong"
    assert body["status"] == "alive"


def test_get_incident_returns_404_when_missing(client_public):
    """
    Situation: Incident not found.
    Expected: Returns 404.
    Function: src.api.routes.get_incident
    """
    client_public.app.state.incident_service.get_incident = AsyncMock(
        return_value=None
    )
    r = client_public.get("/api/v1/incident/INC-NOPE")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_get_incident_returns_incident_when_found(client_public):
    """
    Situation: Incident found.
    Expected: Returns incident data.
    Function: src.api.routes.get_incident
    """
    client_public.app.state.incident_service.get_incident = AsyncMock(
        return_value={"incident_id": "INC-1", "title": "Test"}
    )
    r = client_public.get("/api/v1/incident/INC-1")
    assert r.status_code == 200
    assert r.json()["incident_id"] == "INC-1"


def test_list_incidents_returns_count_and_list(client_public):
    """
    Situation: List incidents called.
    Expected: Returns incidents list with count.
    Function: src.api.routes.list_incidents
    """
    client_public.app.state.incident_service.get_all_incidents = AsyncMock(
        return_value=[{"incident_id": "INC-1"}, {"incident_id": "INC-2"}]
    )
    r = client_public.get("/api/v1/incidents")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert len(body["incidents"]) == 2


def test_list_incidents_respects_limit(client_public):
    """
    Situation: List incidents with limit parameter.
    Expected: Passes limit to service.
    Function: src.api.routes.list_incidents
    """
    client_public.app.state.incident_service.get_all_incidents = AsyncMock(
        return_value=[]
    )
    client_public.get("/api/v1/incidents?limit=10")
    client_public.app.state.incident_service.get_all_incidents.assert_awaited_once_with(10)


def test_list_services_returns_wrapper(client_public):
    """
    Situation: List services called.
    Expected: Returns services list wrapped.
    Function: src.api.routes.list_services
    """
    client_public.app.state.incident_service.list_services = AsyncMock(
        return_value=[{"name": "auth"}]
    )
    r = client_public.get("/api/v1/services")
    assert r.status_code == 200
    assert r.json()["services"] == [{"name": "auth"}]


def test_get_pending_fixes_returns_wrapper(client_public):
    """
    Situation: Get pending fixes called.
    Expected: Returns fixes list with count.
    Function: src.api.routes.get_pending_fixes
    """
    fake_fixes = [{"incident_id": "INC-1", "status": "pr_draft"}]
    with patch("src.api.routes.AutoFixService") as MockAF:
        MockAF.return_value.get_pending_fixes = AsyncMock(return_value=fake_fixes)
        r = client_public.get("/api/v1/fixes/pending")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["fixes"] == fake_fixes


def test_list_oncall_returns_wrapper(client_public):
    """
    Situation: List on-call roster called.
    Expected: Returns roster with count.
    Function: src.api.routes.list_oncall
    """
    fake_roster = [{"name": "Marcus", "role": "primary"}]
    with patch("src.api.routes.OnCallService") as MockOC:
        MockOC.return_value.list_roster = AsyncMock(return_value=fake_roster)
        r = client_public.get("/api/v1/oncall")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["roster"] == fake_roster


def test_list_oncall_passes_service_name(client_public):
    """
    Situation: List on-call with service_name query param.
    Expected: Passes service_name to service.
    Function: src.api.routes.list_oncall
    """
    with patch("src.api.routes.OnCallService") as MockOC:
        MockOC.return_value.list_roster = AsyncMock(return_value=[])
        client_public.get("/api/v1/oncall?service_name=auth")
    MockOC.return_value.list_roster.assert_awaited_once_with("auth")


def test_get_alert_history_returns_wrapper(client_public):
    """
    Situation: Get alert history called.
    Expected: Returns alerts with count.
    Function: src.api.routes.get_alert_history
    """
    fake_alerts = [{"engineer": "Marcus", "status": "sent"}]
    with patch("src.api.routes.AlertService") as MockAlert:
        MockAlert.return_value.get_alert_history = AsyncMock(return_value=fake_alerts)
        r = client_public.get("/api/v1/oncall/alert/history?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    MockAlert.return_value.get_alert_history.assert_awaited_once_with(5)


# ── Auth-required: incident endpoints ───────────────────────────────────

def test_declare_incident_calls_service(client_authed):
    """
    Situation: Valid incident declaration.
    Expected: Calls incident service with payload.
    Function: src.api.routes.declare_incident
    """
    client_authed.app.state.incident_service.declare_incident = AsyncMock(
        return_value={"incident_id": "INC-NEW", "severity": "P1"}
    )
    r = client_authed.post(
        "/api/v1/incident/declare",
        json={"service_name": "payment-api", "message": "UPI failing"},
    )
    assert r.status_code == 200
    assert r.json()["incident_id"] == "INC-NEW"

    call_kwargs = client_authed.app.state.incident_service.declare_incident.call_args.kwargs
    assert call_kwargs["service_name"] == "payment-api"
    assert call_kwargs["message"] == "UPI failing"
    assert call_kwargs["stack_trace"] is None


def test_declare_incident_passes_stack_trace(client_authed):
    """
    Situation: Incident declaration with stack trace.
    Expected: Passes stack trace to service.
    Function: src.api.routes.declare_incident
    """
    client_authed.app.state.incident_service.declare_incident = AsyncMock(
        return_value={"incident_id": "INC-NEW"}
    )
    client_authed.post(
        "/api/v1/incident/declare",
        json={
            "service_name": "payment-api",
            "message": "UPI failing",
            "stack_trace": "java.lang.NullPointerException at Foo.java:42",
        },
    )
    call_kwargs = client_authed.app.state.incident_service.declare_incident.call_args.kwargs
    assert "Foo.java:42" in call_kwargs["stack_trace"]


def test_declare_incident_requires_auth():
    """
    Situation: Declare incident without auth token.
    Expected: Returns 401/403.
    Function: src.api.routes.declare_incident
    """
    app = _make_app()  # No overrides
    c = TestClient(app)
    r = c.post(
        "/api/v1/incident/declare",
        json={"service_name": "x", "message": "y"},
    )
    # The real require_auth will reject the missing token.
    assert r.status_code in (401, 403)


def test_rollback_calls_service(client_authed):
    """
    Situation: Valid rollback request.
    Expected: Calls incident service with incident_id.
    Function: src.api.routes.rollback_incident
    """
    client_authed.app.state.incident_service.rollback = AsyncMock(
        return_value={"incident_id": "INC-1", "status": "rollback_initiated"}
    )
    r = client_authed.post(
        "/api/v1/incident/rollback", json={"incident_id": "INC-1"}
    )
    assert r.status_code == 200
    client_authed.app.state.incident_service.rollback.assert_awaited_once_with("INC-1")


# ── Auth-required: auto-fix endpoints ───────────────────────────────────

def test_approve_fix_returns_result(client_authed):
    """
    Situation: Approve fix succeeds.
    Expected: Returns approval result.
    Function: src.api.routes.approve_fix
    """
    with patch("src.api.routes.AutoFixService") as MockAF:
        MockAF.return_value.approve_fix = AsyncMock(
            return_value={"status": "approved", "pr": {"pr_number": 1}}
        )
        r = client_authed.post("/api/v1/incident/INC-1/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    MockAF.return_value.approve_fix.assert_awaited_once_with("INC-1")


def test_approve_fix_raises_400_on_service_error(client_authed):
    """
    Situation: Approve fix fails with error.
    Expected: Returns 400 with error message.
    Function: src.api.routes.approve_fix
    """
    with patch("src.api.routes.AutoFixService") as MockAF:
        MockAF.return_value.approve_fix = AsyncMock(
            return_value={"error": "No fix found"}
        )
        r = client_authed.post("/api/v1/incident/INC-1/approve")
    assert r.status_code == 400
    assert "No fix found" in r.json()["detail"]


def test_reject_fix_passes_reason(client_authed):
    """
    Situation: Reject fix with reason.
    Expected: Passes reason to service.
    Function: src.api.routes.reject_fix
    """
    with patch("src.api.routes.AutoFixService") as MockAF:
        MockAF.return_value.reject_fix = AsyncMock(
            return_value={"status": "rejected"}
        )
        r = client_authed.post(
            "/api/v1/incident/INC-1/reject", json={"reason": "wrong fix"}
        )
    assert r.status_code == 200
    MockAF.return_value.reject_fix.assert_awaited_once_with("INC-1", "wrong fix")


def test_reject_fix_defaults_to_none_reason(client_authed):
    """
    Situation: Reject fix without reason.
    Expected: Passes None as reason.
    Function: src.api.routes.reject_fix
    """
    with patch("src.api.routes.AutoFixService") as MockAF:
        MockAF.return_value.reject_fix = AsyncMock(
            return_value={"status": "rejected"}
        )
        client_authed.post("/api/v1/incident/INC-1/reject")
    MockAF.return_value.reject_fix.assert_awaited_once_with("INC-1", None)


def test_reject_fix_raises_400_on_error(client_authed):
    """
    Situation: Reject fix fails with error.
    Expected: Returns 400 with error message.
    Function: src.api.routes.reject_fix
    """
    with patch("src.api.routes.AutoFixService") as MockAF:
        MockAF.return_value.reject_fix = AsyncMock(
            return_value={"error": "incident not found"}
        )
        r = client_authed.post("/api/v1/incident/NOPE/reject")
    assert r.status_code == 400


def test_approve_fix_from_ui_returns_result(client_authed):
    """
    Situation: Approve fix from UI endpoint.
    Expected: Returns approval result.
    Function: src.api.routes.approve_fix_from_ui
    """
    with patch("src.api.routes.AutoFixService") as MockAF:
        MockAF.return_value.approve_fix = AsyncMock(
            return_value={"status": "approved"}
        )
        r = client_authed.post("/api/v1/fixes/INC-1/approve")
    assert r.status_code == 200


def test_reject_fix_from_ui(client_authed):
    """
    Situation: Reject fix from UI endpoint.
    Expected: Passes reason to service.
    Function: src.api.routes.reject_fix_from_ui
    """
    with patch("src.api.routes.AutoFixService") as MockAF:
        MockAF.return_value.reject_fix = AsyncMock(
            return_value={"status": "rejected"}
        )
        r = client_authed.post(
            "/api/v1/fixes/INC-1/reject", json={"reason": "duplicate"}
        )
    assert r.status_code == 200
    MockAF.return_value.reject_fix.assert_awaited_once_with("INC-1", "duplicate")


# ── Auth-required: service CRUD ─────────────────────────────────────────

def test_create_service_passes_payload(client_authed):
    """
    Situation: Create service with full payload.
    Expected: Passes payload to service.
    Function: src.api.routes.create_service
    """
    client_authed.app.state.incident_service.add_service = AsyncMock(
        return_value={"status": "created", "name": "new-svc"}
    )
    r = client_authed.post(
        "/api/v1/services",
        json={
            "name": "new-svc",
            "description": "New service",
            "repo_name": "new-svc-repo",
            "dependencies": ["auth"],
            "is_critical": True,
            "on_call": ["@someone"],
        },
    )
    assert r.status_code == 200
    call_payload = client_authed.app.state.incident_service.add_service.call_args.args[0]
    assert call_payload["name"] == "new-svc"
    assert call_payload["dependencies"] == ["auth"]


def test_create_service_raises_400_on_error(client_authed):
    """
    Situation: Create service fails with error.
    Expected: Returns 400 with error message.
    Function: src.api.routes.create_service
    """
    client_authed.app.state.incident_service.add_service = AsyncMock(
        side_effect=ValueError("duplicate name")
    )
    r = client_authed.post("/api/v1/services", json={"name": "existing"})
    assert r.status_code == 400
    assert "duplicate name" in r.json()["detail"]


def test_delete_service(client_authed):
    """
    Situation: Delete service.
    Expected: Calls service delete with name.
    Function: src.api.routes.delete_service
    """
    client_authed.app.state.incident_service.delete_service = AsyncMock(
        return_value={"status": "deleted", "name": "old-svc"}
    )
    r = client_authed.delete("/api/v1/services/old-svc")
    assert r.status_code == 200
    client_authed.app.state.incident_service.delete_service.assert_awaited_once_with("old-svc")


def test_seed_services(client_authed):
    """
    Situation: Seed services.
    Expected: Calls service seed, returns count.
    Function: src.api.routes.seed_services
    """
    client_authed.app.state.incident_service.seed_services = AsyncMock(
        return_value={"status": "seeded", "count": 8}
    )
    r = client_authed.post("/api/v1/services/seed")
    assert r.status_code == 200
    assert r.json()["count"] == 8


# ── Auth-required: on-call management ───────────────────────────────────

def test_add_oncall_member(client_authed):
    """
    Situation: Add on-call member.
    Expected: Passes payload to service.
    Function: src.api.routes.add_oncall_member
    """
    with patch("src.api.routes.OnCallService") as MockOC:
        MockOC.return_value.add_member = AsyncMock(
            return_value={"status": "created", "id": 1}
        )
        r = client_authed.post(
            "/api/v1/oncall/members",
            json={
                "name": "Test User",
                "email": "t@example.com",
                "role": "primary",
                "service_name": "auth",
            },
        )
    assert r.status_code == 200
    MockOC.return_value.add_member.assert_awaited_once()
    call_payload = MockOC.return_value.add_member.call_args.args[0]
    assert call_payload["name"] == "Test User"
    assert call_payload["role"] == "primary"


def test_add_oncall_member_raises_400(client_authed):
    """
    Situation: Add on-call member fails with error.
    Expected: Returns 400 with error message.
    Function: src.api.routes.add_oncall_member
    """
    with patch("src.api.routes.OnCallService") as MockOC:
        MockOC.return_value.add_member = AsyncMock(
            side_effect=ValueError("invalid role")
        )
        r = client_authed.post(
            "/api/v1/oncall/members",
            json={"name": "x", "service_name": "auth"},
        )
    assert r.status_code == 400


def test_remove_oncall_member(client_authed):
    """
    Situation: Remove on-call member.
    Expected: Calls service remove with member_id.
    Function: src.api.routes.remove_oncall_member
    """
    with patch("src.api.routes.OnCallService") as MockOC:
        MockOC.return_value.remove_member = AsyncMock(
            return_value={"status": "deleted"}
        )
        r = client_authed.delete("/api/v1/oncall/members/42")
    assert r.status_code == 200
    MockOC.return_value.remove_member.assert_awaited_once_with(42)


# ── Auth-required: on-call alert (the branching logic) ──────────────────

def test_send_oncall_alert_to_everyone(client_authed):
    """
    Situation: Send alert with everyone=True.
    Expected: Calls alert_everyone.
    Function: src.api.routes.send_oncall_alert
    """
    with patch("src.api.routes.AlertService") as MockAlert:
        MockAlert.return_value.alert_everyone = AsyncMock(
            return_value={"status": "alerted", "count": 5}
        )
        r = client_authed.post(
            "/api/v1/oncall/alert",
            json={"everyone": True, "service_name": "auth"},
        )
    assert r.status_code == 200
    MockAlert.return_value.alert_everyone.assert_awaited_once()


def test_send_oncall_alert_target_everyone_keyword(client_authed):
    """
    Situation: Send alert with target="everyone".
    Expected: Calls alert_everyone (keyword triggers broadcast).
    Function: src.api.routes.send_oncall_alert
    """
    with patch("src.api.routes.AlertService") as MockAlert:
        MockAlert.return_value.alert_everyone = AsyncMock(
            return_value={"status": "alerted"}
        )
        r = client_authed.post(
            "/api/v1/oncall/alert",
            json={"target": "everyone", "service_name": "auth"},
        )
    assert r.status_code == 200
    MockAlert.return_value.alert_everyone.assert_awaited_once()


def test_send_oncall_alert_target_all_keyword(client_authed):
    """
    Situation: Send alert with target="all".
    Expected: Calls alert_everyone (keyword triggers broadcast).
    Function: src.api.routes.send_oncall_alert
    """
    with patch("src.api.routes.AlertService") as MockAlert:
        MockAlert.return_value.alert_everyone = AsyncMock(
            return_value={"status": "alerted"}
        )
        r = client_authed.post(
            "/api/v1/oncall/alert",
            json={"target": "all", "service_name": "auth"},
        )
    assert r.status_code == 200
    MockAlert.return_value.alert_everyone.assert_awaited_once()


def test_send_oncall_alert_to_person(client_authed):
    """
    Situation: Send alert to specific person.
    Expected: Calls alert_person with target.
    Function: src.api.routes.send_oncall_alert
    """
    with patch("src.api.routes.AlertService") as MockAlert:
        MockAlert.return_value.alert_person = AsyncMock(
            return_value={"status": "sent"}
        )
        r = client_authed.post(
            "/api/v1/oncall/alert",
            json={"target": "@marcus", "incident_id": "INC-1"},
        )
    assert r.status_code == 200
    MockAlert.return_value.alert_person.assert_awaited_once()
    call_kwargs = MockAlert.return_value.alert_person.call_args.kwargs
    assert call_kwargs["slack_handle"] == "@marcus"
    assert call_kwargs["incident_id"] == "INC-1"


def test_send_oncall_alert_no_target_no_everyone_returns_400(client_authed):
    """
    Situation: Send alert without target or everyone.
    Expected: Returns 400 with error message.
    Function: src.api.routes.send_oncall_alert
    """
    r = client_authed.post("/api/v1/oncall/alert", json={})
    assert r.status_code == 400
    assert "target" in r.json()["detail"].lower()


def test_send_oncall_alert_default_message_with_incident_id(client_authed):
    """
    Situation: Send alert with incident_id, no custom message.
    Expected: Uses default message with incident_id.
    Function: src.api.routes.send_oncall_alert
    """
    with patch("src.api.routes.AlertService") as MockAlert:
        MockAlert.return_value.alert_person = AsyncMock(
            return_value={"status": "sent"}
        )
        r = client_authed.post(
            "/api/v1/oncall/alert",
            json={"target": "@marcus", "incident_id": "INC-1"},
        )
    call_kwargs = MockAlert.return_value.alert_person.call_args.kwargs
    assert "INC-1" in call_kwargs["message"]


def test_send_oncall_alert_default_message_without_incident_id(client_authed):
    """
    Situation: Send alert without incident_id, no custom message.
    Expected: Uses default page message.
    Function: src.api.routes.send_oncall_alert
    """
    with patch("src.api.routes.AlertService") as MockAlert:
        MockAlert.return_value.alert_person = AsyncMock(
            return_value={"status": "sent"}
        )
        r = client_authed.post(
            "/api/v1/oncall/alert",
            json={"target": "@marcus"},
        )
    call_kwargs = MockAlert.return_value.alert_person.call_args.kwargs
    assert "please acknowledge" in call_kwargs["message"]
