"""
Tests for RAGService.store_outcome and search_similar_outcomes.

The Curator's storage and retrieval layer.

All tests use the real db_session fixture (transaction-wrapped Postgres)
and the real RAGService singleton, with its .model attribute stubbed
to a deterministic encoder. That exercises the real SQL — INSERT,
vector similarity, scoped filters, fallback — without paying the
SentenceTransformer load cost per test.

The singleton reset hook in _reset_rag_singleton is called around each
test so a fake model from one test doesn't leak into the next.
"""
import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from src.services import rag_service as ragmod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

import numpy as np

@pytest.fixture
def fake_rag(db_session, monkeypatch):
    ragmod._reset_rag_singleton()
    svc = ragmod.get_rag_service()

    fake_model = MagicMock()
    fake_model.encode = MagicMock(return_value=np.array([0.1] * 384))
    monkeypatch.setattr(svc, "model", fake_model)
    monkeypatch.setattr(svc, "use_embeddings", True)

    yield svc
    ragmod._reset_rag_singleton()


@pytest.fixture
def no_embeddings(db_session, monkeypatch):
    """RAGService with no model — retrieval should fall back to recency."""
    ragmod._reset_rag_singleton()
    svc = ragmod.get_rag_service()
    monkeypatch.setattr(svc, "model", None)
    monkeypatch.setattr(svc, "use_embeddings", False)
    yield svc
    ragmod._reset_rag_singleton()


async def _insert_outcome(db_session, **overrides):
    defaults = {
        "incident_id": "INC-TEST-001",
        "service_name": "payment-api",
        "repo_name": "payment-service",
        "fix_diff": "--- a\n+++ b\n",
        "verification_passed": True,
        "verification_reason": "tests_passed",
        "human_decision": "approved",
        "human_reason": None,
        "root_cause": "Null deref",
        "suggested_fix": "Guard against None",
        "stack_context": "NullPointerException at Charge.java:88",
        "embedding": "[" + ",".join(["0.1"] * 384) + "]",
    }
    defaults.update(overrides)
    await db_session.execute(
        text("""
            INSERT INTO fix_outcomes (
                incident_id, service_name, repo_name,
                fix_diff, verification_passed, verification_reason,
                human_decision, human_reason,
                root_cause, suggested_fix, stack_context,
                embedding
            ) VALUES (
                :incident_id, :service_name, :repo_name,
                :fix_diff, :verification_passed, :verification_reason,
                :human_decision, :human_reason,
                :root_cause, :suggested_fix, :stack_context,
                CAST(:embedding AS vector)
            )
        """),
        defaults,
    )
    await db_session.flush()
    return defaults["incident_id"]


# ---------------------------------------------------------------------------
# store_outcome
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_outcome_inserts_row(fake_rag, db_session, make_incident):
    iid = await make_incident({"incident_id": "INC-STORE-1"})

    await fake_rag.store_outcome({
        "incident_id": iid,
        "service_name": "payment-api",
        "repo_name": "payment-service",
        "fix_diff": "diff",
        "human_decision": "approved",
        "root_cause": "null check",
        "suggested_fix": "add guard",
        "stack_context": "NPE at line 88",
    })

    row = (await db_session.execute(
        text("SELECT service_name, repo_name, human_decision, embedding IS NOT NULL "
             "FROM fix_outcomes WHERE incident_id = :iid"),
        {"iid": iid},
    )).fetchone()
    assert row is not None
    assert row[0] == "payment-api"
    assert row[1] == "payment-service"
    assert row[2] == "approved"
    assert row[3] is True  # embedding present


@pytest.mark.asyncio
async def test_store_outcome_without_incident_id_skips(fake_rag, db_session):
    """Missing incident_id → no INSERT, warning logged, no exception."""
    await fake_rag.store_outcome({
        "service_name": "payment-api",
        "human_decision": "approved",
    })

    count = (await db_session.execute(
        text("SELECT COUNT(*) FROM fix_outcomes")
    )).scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_store_outcome_survives_db_error(monkeypatch):
    """
    db_error fixture forces every session to raise.
    store_outcome must catch and log, not propagate.
    """
    from src import database as db_module

    class Boom:
        async def __aenter__(self):
            raise RuntimeError("forced DB error")
        async def __aexit__(self, *a):
            return False

    ragmod._reset_rag_singleton()
    svc = ragmod.get_rag_service()
    monkeypatch.setattr(svc, "model", None)
    monkeypatch.setattr(svc, "use_embeddings", False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", Boom)

    # Should not raise
    await svc.store_outcome({
        "incident_id": "INC-1",
        "service_name": "payment-api",
        "human_decision": "approved",
    })

    ragmod._reset_rag_singleton()


@pytest.mark.asyncio
async def test_store_outcome_embedding_text_shape(fake_rag, db_session, make_incident):
    """
    The text handed to model.encode must be root_cause + suggested_fix
    + stack_context, matching what store_incident builds.
    """
    iid = await make_incident({"incident_id": "INC-STORE-2"})

    await fake_rag.store_outcome({
        "incident_id": iid,
        "service_name": "payment-api",
        "human_decision": "approved",
        "root_cause": "ROOTCAUSE_TOKEN",
        "suggested_fix": "SUGGESTED_TOKEN",
        "stack_context": "STACK_TOKEN",
    })

    call_args = fake_rag.model.encode.call_args
    encoded = call_args.args[0]
    assert "ROOTCAUSE_TOKEN" in encoded
    assert "SUGGESTED_TOKEN" in encoded
    assert "STACK_TOKEN" in encoded


@pytest.mark.asyncio
async def test_store_outcome_with_missing_embedding_text(fake_rag, db_session, make_incident):
    """
    Outcome with no root_cause / suggested_fix / stack_context.
    Embedding text is empty string; still inserts (embedding may be
    a valid vector over empty text).
    """
    iid = await make_incident({"incident_id": "INC-STORE-3"})
    await fake_rag.store_outcome({
        "incident_id": iid,
        "service_name": "payment-api",
        "human_decision": "rejected",
        "human_reason": "wrong approach",
    })

    row = (await db_session.execute(
        text("SELECT human_decision, human_reason FROM fix_outcomes WHERE incident_id = :iid"),
        {"iid": iid},
    )).fetchone()
    assert row[0] == "rejected"
    assert row[1] == "wrong approach"


# ---------------------------------------------------------------------------
# search_similar_outcomes — scoping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_returns_same_service_outcomes(fake_rag, db_session, make_incident):
    iid_a = await make_incident({"incident_id": "INC-A"})
    iid_b = await make_incident({"incident_id": "INC-B"})
    iid_c = await make_incident({"incident_id": "INC-C"})

    await _insert_outcome(db_session, incident_id=iid_a, service_name="payment-api")
    await _insert_outcome(db_session, incident_id=iid_b, service_name="payment-api")
    await _insert_outcome(db_session, incident_id=iid_c, service_name="auth")

    results = await fake_rag.search_similar_outcomes(
        query="null check at line 88",
        service_name="payment-api",
        repo_name="payment-service",
        limit=3,
    )

    services = {r["service_name"] for r in results}
    assert services == {"payment-api"}
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_excludes_other_services(fake_rag, db_session, make_incident):
    """No same-service outcomes, no repo fallback available → []."""
    iid = await make_incident({"incident_id": "INC-OTHER"})
    await _insert_outcome(db_session, incident_id=iid, service_name="auth")

    results = await fake_rag.search_similar_outcomes(
        query="anything",
        service_name="payment-api",
        repo_name=None,  # no repo fallback
        limit=3,
    )
    assert results == []


@pytest.mark.asyncio
async def test_search_no_fallback_when_service_has_results(
    fake_rag, db_session, make_incident
):
    """
    Same-service has results, even if fewer than limit.
    No repo fallback fires — same-service is preferred exclusively.
    """
    iid1 = await make_incident({"incident_id": "INC-S1"})
    iid2 = await make_incident({"incident_id": "INC-S2"})
    iid3 = await make_incident({"incident_id": "INC-S3"})

    await _insert_outcome(db_session, incident_id=iid1,
                          service_name="payment-api", repo_name="payment-service")
    await _insert_outcome(db_session, incident_id=iid2,
                          service_name="ledger", repo_name="payment-service")
    await _insert_outcome(db_session, incident_id=iid3,
                          service_name="refund", repo_name="payment-service")

    results = await fake_rag.search_similar_outcomes(
        query="null check",
        service_name="payment-api",
        repo_name="payment-service",
        limit=3,
    )

    assert len(results) == 1
    assert results[0]["service_name"] == "payment-api"


@pytest.mark.asyncio
async def test_search_falls_back_to_repo_when_service_empty(
    fake_rag, db_session, make_incident
):
    """
    Zero same-service outcomes, two same-repo outcomes under
    different services → fallback fills up to limit.
    """
    iid1 = await make_incident({"incident_id": "INC-R1"})
    iid2 = await make_incident({"incident_id": "INC-R2"})

    await _insert_outcome(db_session, incident_id=iid1,
                          service_name="ledger", repo_name="payment-service")
    await _insert_outcome(db_session, incident_id=iid2,
                          service_name="refund", repo_name="payment-service")

    results = await fake_rag.search_similar_outcomes(
        query="null check",
        service_name="payment-api",
        repo_name="payment-service",
        limit=3,
    )

    assert len(results) == 2
    services = {r["service_name"] for r in results}
    assert services == {"ledger", "refund"}


@pytest.mark.asyncio
async def test_search_no_global_scope(fake_rag, db_session, make_incident):
    """
    Outcomes exist for services unrelated to the query. Even with
    matching embedding text, they must not be returned.
    """
    iid = await make_incident({"incident_id": "INC-UNRELATED"})
    await _insert_outcome(db_session, incident_id=iid,
                          service_name="auth", repo_name="auth-service",
                          root_cause="Null deref", suggested_fix="Guard")

    results = await fake_rag.search_similar_outcomes(
        query="Null deref Guard",
        service_name="payment-api",
        repo_name="payment-service",
        limit=3,
    )
    assert results == []


@pytest.mark.asyncio
async def test_search_empty_query_returns_empty(fake_rag, db_session):
    results = await fake_rag.search_similar_outcomes(
        query="", service_name="payment-api", limit=3,
    )
    assert results == []


@pytest.mark.asyncio
async def test_search_empty_service_returns_empty(fake_rag, db_session):
    results = await fake_rag.search_similar_outcomes(
        query="anything", service_name="", limit=3,
    )
    assert results == []


@pytest.mark.asyncio
async def test_search_returns_shaped_dict(fake_rag, db_session, make_incident):
    """Row shape matches the contract the caller expects."""
    iid = await make_incident({"incident_id": "INC-SHAPE"})
    await _insert_outcome(db_session, incident_id=iid,
                          service_name="payment-api",
                          human_decision="approved",
                          verification_passed=True,
                          verification_reason="tests_passed")

    results = await fake_rag.search_similar_outcomes(
        query="null check",
        service_name="payment-api",
        repo_name="payment-service",
        limit=3,
    )
    assert len(results) == 1
    row = results[0]
    assert set(row.keys()) >= {
        "id", "incident_id", "service_name", "repo_name",
        "root_cause", "suggested_fix", "fix_diff",
        "verification_passed", "human_decision", "human_reason",
        "similarity",
    }
    assert row["human_decision"] == "approved"
    assert row["verification_passed"] is True


# ---------------------------------------------------------------------------
# search_similar_outcomes — degradation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_falls_back_to_recency_without_embeddings(
    no_embeddings, db_session, make_incident
):
    """
    No model → still scopes and filters, ordered by created_at DESC,
    similarity fixed at 0.5.
    """
    iid1 = await make_incident({"incident_id": "INC-R1"})
    iid2 = await make_incident({"incident_id": "INC-R2"})
    await _insert_outcome(db_session, incident_id=iid1, service_name="payment-api")
    await _insert_outcome(db_session, incident_id=iid2, service_name="payment-api")

    results = await no_embeddings.search_similar_outcomes(
        query="anything",
        service_name="payment-api",
        repo_name=None,
        limit=3,
    )
    assert len(results) == 2
    assert all(r["similarity"] == 0.5 for r in results)
