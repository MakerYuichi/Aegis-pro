"""
End-to-end integration test for the Curator loop.

Scenario:
  1. An incident exists with an approved+verified fix outcome
     recorded in fix_outcomes.
  2. A new incident for the same service is declared with
     CURATOR_FEW_SHOT=true.
  3. The Curator should retrieve the outcome, format it, and pass it
     to the LLM as fix_outcomes_context.

What this exercises end to end:
  - search_similar_outcomes querying the real DB
  - format_outcomes_for_prompt rendering the retrieved row
  - _stage_investigator threading the formatted context through
  - LLMService.analyze_incident receiving it

What it mocks:
  - The LLM provider (no API calls)
  - The Docker verifier (VERIFY_BEFORE_REPORT=false)
  - GitHub (no network)
  - Alerts, K8s, WebSocket (side effects not under test)

Real components:
  - Postgres (the db_session fixture)
  - RAGService singleton (with .model stubbed for a deterministic encoder)
  - IncidentService
  - The full declare_incident pipeline
"""
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from sqlalchemy import text

from src.services import rag_service as ragmod
from src.services.incident_service import IncidentService


@pytest.fixture
def fake_rag_model(db_session, monkeypatch):
    """
    Real RAGService against the test transaction, .model stubbed.
    Same pattern as test_rag_outcomes.py.
    """
    ragmod._reset_rag_singleton()

    def _no_model_init(self):
        self.model = None
        self.use_embeddings = False
        self.executor = ThreadPoolExecutor(max_workers=1)

    monkeypatch.setattr(ragmod.RAGService, "__init__", _no_model_init)
    svc = ragmod.get_rag_service()

    fake_model = MagicMock()
    # Non-uniform vector so similarity ordering is meaningful.
    fake_model.encode = MagicMock(
        side_effect=lambda text: np.array(
            [0.5 + (hash(text) % 100) / 1000.0] * 384
        )
    )
    monkeypatch.setattr(svc, "model", fake_model)
    monkeypatch.setattr(svc, "use_embeddings", True)

    yield svc
    ragmod._reset_rag_singleton()


@pytest.mark.asyncio
async def test_curator_loop_end_to_end(
    db_session, make_incident, seeded_services, fake_rag_model, monkeypatch
):
    """
    A previously-approved outcome is retrieved and injected into the
    prompt for a new incident on the same service.
    """
    # --- Setup: an incident with an approved outcome in the DB ---

    old_incident = await make_incident({
        "incident_id": "INC-OLD",
        "service_name": "payment-api",
        "root_cause": "Null deref in charge handler",
        "suggested_fix": "Add null guard before method call",
    })

    await db_session.execute(
        text("""
            INSERT INTO fix_outcomes (
                incident_id, service_name, repo_name,
                fix_diff, verification_passed, verification_reason,
                human_decision, human_reason,
                root_cause, suggested_fix, stack_context
            ) VALUES (
                :incident_id, :service_name, :repo_name,
                :fix_diff, :verified, :verify_reason,
                :decision, :reason,
                :root_cause, :suggested_fix, :stack_context
            )
        """),
        {
            "incident_id": old_incident,
            "service_name": "payment-api",
            "repo_name": "payment-service",
            "fix_diff": "--- a/Charge.java\n+++ b/Charge.java\n-return x.y();\n+if (x != null) return x.y();",
            "verified": True,
            "verify_reason": "tests_passed",
            "decision": "approved",
            "reason": None,
            "root_cause": "Null deref in charge handler",
            "suggested_fix": "Add null guard before method call",
            "stack_context": "NPE at Charge.java:88",
        },
    )
    await db_session.flush()

    # Recompute the outcome's embedding via the stubbed model so the
    # retrieval query can rank it against the new incident.
    outcome_row = (await db_session.execute(
        text("SELECT id, root_cause, suggested_fix, stack_context FROM fix_outcomes WHERE incident_id = :iid"),
        {"iid": old_incident},
    )).fetchone()
    text_to_embed = " ".join(filter(None, [outcome_row[1], outcome_row[2], outcome_row[3]]))
    embedding = fake_rag_model.model.encode(text_to_embed)
    embedding_str = "[" + ",".join(str(x) for x in embedding.tolist()) + "]"
    await db_session.execute(
        text("UPDATE fix_outcomes SET embedding = CAST(:e AS vector) WHERE id = :id"),
        {"e": embedding_str, "id": outcome_row[0]},
    )
    await db_session.flush()

    # --- Enable the Curator flag for this test only ---

    monkeypatch.setattr(
        "src.services.incident_service.settings.CURATOR_FEW_SHOT", True
    )
    monkeypatch.setattr(
        "src.services.incident_service.settings.CURATOR_MAX_OUTCOMES", 3
    )
    # Make sure the verifier is off so we don't try to run Docker.
    monkeypatch.setattr(
        "src.services.incident_service.settings.VERIFY_BEFORE_REPORT", False
    )

    # --- Run declare_incident with the LLM stubbed so we can inspect the prompt ---

    svc = IncidentService()

    captured = {}

    async def fake_analyze(*args, **kwargs):
        captured.update(kwargs)
        return {
            "severity": "P1",
            "title": "payment-api incident",
            "root_cause": "Something broke",
            "suggested_fix": "Fix it",
            "rollback_command": "kubectl rollout undo deploy/payment-api",
            "confidence": 0.85,
        }

    with patch.object(svc.llm, "analyze_incident", side_effect=fake_analyze), \
         patch("src.services.incident_service.get_github_service") as gh, \
         patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws, \
         patch("src.services.incident_service.AutoFixService") as AF:

        gh.return_value.get_recent_prs = AsyncMock(return_value=[])
        gh.return_value.get_blame_with_pr = AsyncMock(return_value=None)
        gh.return_value.get_file_content = AsyncMock(return_value=None)
        gh.return_value.get_related_prs = AsyncMock(return_value=[])
        OnCall.return_value.get_on_call = AsyncMock(
            return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()
        AF.return_value.generate_fix = AsyncMock(
            return_value={"status": "fix_generated", "fix": "diff"})

        await svc.declare_incident(
            service_name="payment-api",
            message="NullPointerException in charge handler",
        )

    # --- Assert the outcome reached the prompt ---

    assert "fix_outcomes_context" in captured, "analyze_incident was not called"
    context = captured["fix_outcomes_context"]
    assert "FEW-SHOT EXAMPLES" in context
    assert "APPROVED, tests passed" in context
    assert "Null deref in charge handler" in context
    assert "Add null guard before method call" in context


@pytest.mark.asyncio
async def test_curator_loop_empty_when_no_outcomes(
    db_session, make_incident, seeded_services, fake_rag_model, monkeypatch
):
    """
    No past outcomes → fix_outcomes_context is empty, pipeline still
    completes successfully.
    """
    monkeypatch.setattr(
        "src.services.incident_service.settings.CURATOR_FEW_SHOT", True
    )
    monkeypatch.setattr(
        "src.services.incident_service.settings.VERIFY_BEFORE_REPORT", False
    )

    svc = IncidentService()
    captured = {}

    async def fake_analyze(*args, **kwargs):
        captured.update(kwargs)
        return {
            "severity": "P1", "title": "t", "root_cause": "r",
            "suggested_fix": "f", "rollback_command": "k", "confidence": 0.5,
        }

    with patch.object(svc.llm, "analyze_incident", side_effect=fake_analyze), \
         patch("src.services.incident_service.get_github_service"), \
         patch("src.services.incident_service.OnCallService") as OnCall, \
         patch("src.services.incident_service.AlertService") as Alert, \
         patch("src.services.incident_service.KubernetesService") as K8s, \
         patch("src.services.incident_service.manager") as ws, \
         patch("src.services.incident_service.AutoFixService") as AF:

        OnCall.return_value.get_on_call = AsyncMock(
            return_value={"primary": None, "secondary": None, "tertiary": None})
        OnCall.return_value.get_escalation_policy = AsyncMock(return_value=[])
        Alert.return_value.send_alerts = AsyncMock()
        K8s.return_value.get_deployment_status = AsyncMock(return_value="ok")
        ws.broadcast = AsyncMock()
        AF.return_value.generate_fix = AsyncMock(
            return_value={"status": "fix_generated", "fix": "diff"})

        await svc.declare_incident(
            service_name="payment-api",
            message="fresh incident",
        )

    assert captured.get("fix_outcomes_context", "") == ""
