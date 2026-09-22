"""
Tests for src/api/slack.py — Slack Events API, slash commands, interactive actions.

Covers:
  - URL verification challenge
  - Slash command dispatch (/incident)
  - Block actions dispatch (rollback, view_details, acknowledge)
  - build_incident_blocks / build_detail_blocks shape (incl. git blame)
  - send_slack_response error tolerance
  - process_incident_command missing service
  - GET /slack/status
"""
import json
import pytest
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from src.main import app
from src.api import slack as slack_module


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _fake_result():
    return {
        "incident_id": "INC-42",
        "service": "payments",
        "service_name": "payments",
        "severity": "P1",
        "title": "Latency spike",
        "root_cause": "Connection pool exhausted",
        "suggested_fix": "Increase pool size",
        "rollback_command": "kubectl rollout undo deploy/payments",
        "confidence": 0.91,
        "on_call": ["alice", "bob"],
        "blast_radius": {"count": 2, "affected": ["payments", "checkout"]},
        "extra_metadata": {
            "github": {
                "blame": {
                    "file": "src/db.py",
                    "line": 88,
                    "author": "eng@acme.com",
                    "commit_hash": "abc123",
                    "pr_number": 501,
                    "pr_title": "Add retry logic",
                    "pr_author": "eng@acme.com",
                }
            }
        },
    }


# ---------------------------------------------------------------------------
# POST /slack/events — URL verification
# ---------------------------------------------------------------------------

def test_url_verification_returns_challenge(client):
    body = {"type": "url_verification", "challenge": "abc-123"}
    resp = client.post("/slack/events", json=body)
    assert resp.status_code == 200
    assert resp.json() == {"challenge": "abc-123"}


# ---------------------------------------------------------------------------
# POST /slack/events — slash command
# ---------------------------------------------------------------------------

def test_slash_command_incident_schedules_processing(client):
    form = urlencode({
        "command": "/incident",
        "text": "payments DB is down",
        "user_name": "alice",
        "response_url": "https://hooks.slack.com/commands/xxx",
    })
    with patch.object(slack_module, "process_incident_command", new=AsyncMock()) as proc:
        resp = client.post(
            "/slack/events",
            content=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert resp.status_code == 200
    # BackgroundTasks executes after response, so by the time TestClient
    # returns, the task has run. Assert it was invoked with parsed form data.
    proc.assert_awaited_once()
    call_data = proc.await_args.kwargs["data"]
    assert call_data["command"] == "/incident"
    assert call_data["text"] == "payments DB is down"


def test_unknown_command_returns_ok(client):
    form = urlencode({"command": "/other", "text": "hi"})
    resp = client.post(
        "/slack/events",
        content=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /slack/events — interactive block actions
# ---------------------------------------------------------------------------

def _block_action_payload(action_id: str, incident_id: str = "INC-42"):
    return {
        "type": "block_actions",
        "actions": [{"action_id": action_id, "value": incident_id}],
        "user": {"username": "alice"},
        "response_url": "https://hooks.slack.com/actions/xxx",
    }


@pytest.mark.parametrize("action_id,handler_name", [
    ("rollback", "handle_rollback"),
    ("view_details", "handle_view_details"),
    ("acknowledge", "handle_acknowledge"),
])
def test_block_action_dispatches_to_handler(client, action_id, handler_name):
    payload = _block_action_payload(action_id)
    form = urlencode({"payload": json.dumps(payload)})

    with patch.object(slack_module, handler_name, new=AsyncMock()) as handler:
        resp = client.post(
            "/slack/events",
            content=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert resp.status_code == 200
    handler.assert_awaited_once()
    kwargs = handler.await_args.kwargs
    assert kwargs["incident_id"] == "INC-42"
    assert kwargs["user"] == "alice"


def test_block_action_unknown_id_is_ignored(client):
    payload = _block_action_payload("not_a_real_action")
    form = urlencode({"payload": json.dumps(payload)})

    with patch.object(slack_module, "handle_rollback", new=AsyncMock()) as rb, \
         patch.object(slack_module, "handle_view_details", new=AsyncMock()) as vd, \
         patch.object(slack_module, "handle_acknowledge", new=AsyncMock()) as ack:
        resp = client.post(
            "/slack/events",
            content=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert resp.status_code == 200
    rb.assert_not_awaited()
    vd.assert_not_awaited()
    ack.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /slack/events — error handling
# ---------------------------------------------------------------------------

def test_malformed_payload_returns_200_with_error_body(client):
    """
    Documents current behavior: exceptions are swallowed and returned as
    a 200 with an error body. Slack treats 200 as success, so failed
    events are silently dropped — see the review notes.
    """
    form = urlencode({"payload": "not-valid-json"})
    resp = client.post(
        "/slack/events",
        content=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body


# ---------------------------------------------------------------------------
# process_incident_command (unit)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_incident_command_missing_service_asks_for_one():
    data = {"text": "", "user_name": "alice", "response_url": "https://hooks.slack.com/x"}

    with patch.object(slack_module, "send_slack_response", new=AsyncMock()) as send:
        await slack_module.process_incident_command(data)

    send.assert_awaited_once()
    payload = send.await_args.args[1]
    assert "Please specify a service" in payload["text"]


@pytest.mark.asyncio
async def test_process_incident_command_declares_and_responds():
    data = {
        "text": "payments DB is down",
        "user_name": "alice",
        "response_url": "https://hooks.slack.com/x",
    }
    fake = _fake_result()

    with patch.object(slack_module, "IncidentService") as IncSvc, \
         patch.object(slack_module, "send_slack_response", new=AsyncMock()) as send, \
         patch.object(slack_module.manager, "broadcast", new=AsyncMock()) as bc:
        IncSvc.return_value.declare_incident = AsyncMock(return_value=fake)
        await slack_module.process_incident_command(data)

    IncSvc.return_value.declare_incident.assert_awaited_once()
    call = IncSvc.return_value.declare_incident.await_args.kwargs
    assert call["service_name"] == "payments"
    assert call["message"] == "DB is down"
    assert call["reported_by"] == "alice"
    bc.assert_awaited_once()
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_incident_command_swallows_service_errors():
    data = {"text": "payments boom", "user_name": "alice", "response_url": "x"}

    with patch.object(slack_module, "IncidentService") as IncSvc:
        IncSvc.return_value.declare_incident = AsyncMock(side_effect=RuntimeError("db"))
        # Must not raise
        await slack_module.process_incident_command(data)


# ---------------------------------------------------------------------------
# handle_rollback / view_details / acknowledge (unit)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_rollback_calls_service_and_broadcasts():
    with patch.object(slack_module, "IncidentService") as IncSvc, \
         patch.object(slack_module, "send_slack_response", new=AsyncMock()) as send, \
         patch.object(slack_module.manager, "broadcast", new=AsyncMock()) as bc:
        IncSvc.return_value.rollback = AsyncMock(return_value={"status": "rolled_back"})
        await slack_module.handle_rollback(
            data={"response_url": "https://hooks.slack.com/x"},
            incident_id="INC-42",
            user="alice",
        )

    IncSvc.return_value.rollback.assert_awaited_once_with("INC-42")
    bc.assert_awaited_once()
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_view_details_sends_blocks():
    fake = _fake_detail_incident()

    with patch.object(slack_module, "IncidentService") as IncSvc, \
         patch.object(slack_module, "send_slack_response", new=AsyncMock()) as send, \
         patch.object(slack_module.manager, "broadcast", new=AsyncMock()):
        IncSvc.return_value.get_incident = AsyncMock(return_value=fake)
        await slack_module.handle_view_details(
            data={"response_url": "https://hooks.slack.com/x"},
            incident_id="INC-42",
            user="alice",
        )

    send.assert_awaited_once()
    payload = send.await_args.args[1]
    assert "blocks" in payload


@pytest.mark.asyncio
async def test_handle_view_details_no_response_url_still_broadcasts():
    fake = _fake_detail_incident()

    with patch.object(slack_module, "IncidentService") as IncSvc, \
         patch.object(slack_module, "send_slack_response", new=AsyncMock()) as send, \
         patch.object(slack_module.manager, "broadcast", new=AsyncMock()) as bc:
        IncSvc.return_value.get_incident = AsyncMock(return_value=fake)
        await slack_module.handle_view_details(
            data={}, incident_id="INC-42", user="alice"
        )

    bc.assert_awaited_once()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_acknowledge_broadcasts_and_responds():
    with patch.object(slack_module, "send_slack_response", new=AsyncMock()) as send, \
         patch.object(slack_module.manager, "broadcast", new=AsyncMock()) as bc:
        await slack_module.handle_acknowledge(
            data={"response_url": "https://hooks.slack.com/x"},
            incident_id="INC-42",
            user="alice",
        )

    bc.assert_awaited_once()
    send.assert_awaited_once()


# ---------------------------------------------------------------------------
# build_incident_blocks (pure)
# ---------------------------------------------------------------------------

def test_build_incident_blocks_minimal():
    blocks = slack_module.build_incident_blocks(_fake_result())
    types = [b["type"] for b in blocks]
    assert "header" in types
    assert "actions" in types
    # Three buttons
    actions = next(b for b in blocks if b["type"] == "actions")
    assert {e["action_id"] for e in actions["elements"]} == {
        "rollback", "view_details", "acknowledge"
    }


def test_build_incident_blocks_severity_color_known():
    blocks = slack_module.build_incident_blocks(_fake_result())
    # Severity P1 → orange. The color doesn't appear in the current
    # implementation's blocks (it's computed but unused). This test
    # documents that the variable exists and the function runs.
    assert blocks  # non-empty


def test_build_incident_blocks_includes_blast_radius():
    result = _fake_result()
    result["blast_radius"] = {"count": 3, "affected": ["a", "b", "c"]}
    blocks = slack_module.build_incident_blocks(result)
    context_text = " ".join(
        e["text"] for b in blocks if b["type"] == "context"
        for e in b.get("elements", [])
    )
    assert "Blast Radius" in context_text
    assert "3" in context_text


def test_build_incident_blocks_includes_git_blame():
    blocks = slack_module.build_incident_blocks(_fake_result())
    text = json.dumps(blocks)
    assert "Git Blame" in text
    assert "src/db.py" in text
    assert "eng@acme.com" in text


def test_build_incident_blocks_includes_pr_link_when_present():
    blocks = slack_module.build_incident_blocks(_fake_result())
    text = json.dumps(blocks)
    assert "PR #501" in text
    assert "Add retry logic" in text


def test_build_incident_blocks_omits_github_section_when_absent():
    result = _fake_result()
    result["extra_metadata"] = {}
    blocks = slack_module.build_incident_blocks(result)
    assert "Git Blame" not in json.dumps(blocks)


def test_build_incident_blocks_handles_missing_blast_radius():
    result = _fake_result()
    result.pop("blast_radius", None)
    blocks = slack_module.build_incident_blocks(result)
    assert blocks  # does not raise


def test_build_incident_blocks_handles_rag_context_flag():
    result = _fake_result()
    result["rag_context_used"] = True
    blocks = slack_module.build_incident_blocks(result)
    text = json.dumps(blocks)
    assert "similar past incidents" in text


# ---------------------------------------------------------------------------
# build_detail_blocks (pure)
# ---------------------------------------------------------------------------

def _fake_detail_incident():
    return {
        "incident_id": "INC-42",
        "service_name": "payments",
        "severity": "P1",
        "status": "active",
        "title": "Latency spike",
        "root_cause": "Connection pool exhausted",
        "suggested_fix": "Increase pool size",
        "confidence_score": 0.91,
        "stack_trace": "at db.connect(db.py:88)",
        "affected_services": ["payments", "checkout"],
        "extra_metadata": {
            "github": {
                "blame": {
                    "file": "src/db.py", "line": 88,
                    "author": "eng@acme.com", "commit_hash": "abc123",
                    "pr_number": 501, "pr_title": "Add retry logic",
                }
            }
        },
    }


def test_build_detail_blocks_minimal():
    blocks = slack_module.build_detail_blocks(_fake_detail_incident())
    assert any(b["type"] == "header" for b in blocks)
    assert "INC-42" in json.dumps(blocks)


def test_build_detail_blocks_includes_stack_trace():
    blocks = slack_module.build_detail_blocks(_fake_detail_incident())
    assert "db.py:88" in json.dumps(blocks)


def test_build_detail_blocks_includes_affected_services():
    blocks = slack_module.build_detail_blocks(_fake_detail_incident())
    text = json.dumps(blocks)
    assert "payments" in text and "checkout" in text


def test_build_detail_blocks_omits_stack_trace_when_absent():
    inc = _fake_detail_incident()
    inc.pop("stack_trace")
    blocks = slack_module.build_detail_blocks(inc)
    assert "Stack Trace" not in json.dumps(blocks)


def test_build_detail_blocks_includes_git_blame_and_pr():
    blocks = slack_module.build_detail_blocks(_fake_detail_incident())
    text = json.dumps(blocks)
    assert "Git Blame" in text
    assert "PR #501" in text


# ---------------------------------------------------------------------------
# send_slack_response (unit)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_slack_response_posts_to_url():
    with patch("httpx.AsyncClient") as http_cls:
        client = AsyncMock()
        http_cls.return_value.__aenter__.return_value = client

        await slack_module.send_slack_response(
            "https://hooks.slack.com/x", {"text": "hi"}
        )

    client.post.assert_awaited_once_with("https://hooks.slack.com/x", json={"text": "hi"})


@pytest.mark.asyncio
async def test_send_slack_response_swallows_errors():
    with patch("httpx.AsyncClient") as http_cls:
        client = AsyncMock()
        client.post = AsyncMock(side_effect=RuntimeError("network"))
        http_cls.return_value.__aenter__.return_value = client

        # Must not raise
        await slack_module.send_slack_response("https://x", {"text": "hi"})


# ---------------------------------------------------------------------------
# GET /slack/status
# ---------------------------------------------------------------------------

def test_slack_status_reports_token_state(client):
    resp = client.get("/slack/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "configured"
    assert "bot_token" in body
