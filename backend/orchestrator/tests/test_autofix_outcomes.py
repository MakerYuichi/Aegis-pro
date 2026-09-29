"""
Tests for AutoFixService._record_outcome and its wiring into
approve_fix / reject_fix.

The Curator's write site. Every human approve/reject must produce one
fix_outcomes row, and a failure to write must not turn a successful
human action into an error for the caller.

Uses the real db_session fixture and the real RAGService singleton
with a stubbed .model (see test_rag_outcomes.py for the pattern).
"""
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from sqlalchemy import text

from src.services import rag_service as ragmod
from src.services.autofix_service import AutoFixService


@pytest.fixture
def fake_rag(db_session, monkeypatch):
    """
    Real RAGService against the test transaction, .model stubbed.
    __init__ is patched so the real SentenceTransformer doesn't load.
    """
    ragmod._reset_rag_singleton()

    def _no_model_init(self):
        self.model = None
        self.use_embeddings = False
        self.executor = ThreadPoolExecutor(max_workers=1)

    monkeypatch.setattr(ragmod.RAGService, "__init__", _no_model_init)
    svc = ragmod.get_rag_service()

    fake_model = MagicMock()
    fake_model.encode = MagicMock(return_value=np.array([0.1] * 384))
    monkeypatch.setattr(svc, "model", fake_model)
    monkeypatch.setattr(svc, "use_embeddings", True)

    yield svc
    ragmod._reset_rag_singleton()


@pytest.fixture
def autofix_with_incident(db_session, make_incident, fake_rag):
    """
    Insert an incident with an auto_fix in extra_metadata and return
    (service, incident_id). The service is a real AutoFixService whose
    github client is stubbed (it's constructed in __init__).
    """
    with patch("src.services.autofix_service.get_github_service"), \
         patch("src.services.autofix_service.LLMService"):
        svc = AutoFixService()

    async def _build(**overrides):
        iid = await make_incident({
            "incident_id": overrides.pop("incident_id", "INC-AUTOFIX-1"),
            "service_name": "payment-api",
            "root_cause": "Null deref",
            "suggested_fix": "Add guard",
            "extra_metadata": json.dumps({
                "auto_fix": {
                    "status": "fix_generated",
                    "fix": "--- a\n+++ b\n",
                    "repo_name": "payment-service",
                    "requires_approval": True,
                },
                "verification": {
                    "passed": True,
                    "reason": "tests_passed",
                },
            }),
        })
        return iid

    return svc, _build


# ---------------------------------------------------------------------------
# _record_outcome
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_outcome_writes_row(
    autofix_with_incident, db_session
):
    svc, build = autofix_with_incident
    iid = await build()

    incident = {
        "incident_id": iid,
        "service_name": "payment-api",
        "root_cause": "Null deref",
        "suggested_fix": "Add guard",
        "stack_trace": "NPE at line 88",
        "extra_metadata": json.dumps({"verification": {"passed": True, "reason": "tests_passed"}}),
    }

    await svc._record_outcome(
        incident=incident,
        auto_fix={"fix": "--- a\n+++ b\n", "repo_name": "payment-service"},
        human_decision="approved",
        human_reason=None,
    )

    row = (await db_session.execute(
        text("""SELECT service_name, repo_name, human_decision,
                       verification_passed, verification_reason
                FROM fix_outcomes WHERE incident_id = :iid"""),
        {"iid": iid},
    )).fetchone()
    assert row is not None
    assert row[0] == "payment-api"
    assert row[1] == "payment-service"
    assert row[2] == "approved"
    assert row[3] is True
    assert row[4] == "tests_passed"


@pytest.mark.asyncio
async def test_record_outcome_rejected_with_reason(
    autofix_with_incident, db_session
):
    svc, build = autofix_with_incident
    iid = await build(incident_id="INC-AUTOFIX-2")

    await svc._record_outcome(
        incident={
            "incident_id": iid,
            "service_name": "payment-api",
            "extra_metadata": json.dumps({}),
        },
        auto_fix={"fix": "diff", "repo_name": "payment-service"},
        human_decision="rejected",
        human_reason="wrong approach",
    )

    row = (await db_session.execute(
        text("SELECT human_decision, human_reason FROM fix_outcomes WHERE incident_id = :iid"),
        {"iid": iid},
    )).fetchone()
    assert row[0] == "rejected"
    assert row[1] == "wrong approach"


@pytest.mark.asyncio
async def test_record_outcome_missing_incident_id_skips(
    autofix_with_incident, db_session
):
    svc, _ = autofix_with_incident

    await svc._record_outcome(
        incident={},
        auto_fix={"fix": "diff"},
        human_decision="approved",
    )

    count = (await db_session.execute(text("SELECT COUNT(*) FROM fix_outcomes"))).scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_record_outcome_survives_store_failure(
    autofix_with_incident, monkeypatch
):
    """
    RAGService.store_outcome raising must not propagate.
    """
    svc, _ = autofix_with_incident

    async def boom(*a, **k):
        raise RuntimeError("store failed")

    fake_rag = MagicMock()
    fake_rag.store_outcome = AsyncMock(side_effect=boom)

    with patch("src.services.rag_service.get_rag_service", return_value=fake_rag):
        # Should not raise
        await svc._record_outcome(
            incident={"incident_id": "INC-1", "service_name": "x"},
            auto_fix={"fix": "diff"},
            human_decision="approved",
        )


@pytest.mark.asyncio
async def test_record_outcome_reads_verification_from_metadata(
    autofix_with_incident, db_session
):
    svc, build = autofix_with_incident
    iid = await build(incident_id="INC-AUTOFIX-3")

    await svc._record_outcome(
        incident={
            "incident_id": iid,
            "service_name": "payment-api",
            "extra_metadata": json.dumps({
                "verification": {"passed": False, "reason": "tests_failed"},
            }),
        },
        auto_fix={"fix": "diff"},
        human_decision="rejected",
        human_reason="broken",
    )

    row = (await db_session.execute(
        text("SELECT verification_passed, verification_reason FROM fix_outcomes WHERE incident_id = :iid"),
        {"iid": iid},
    )).fetchone()
    assert row[0] is False
    assert row[1] == "tests_failed"


@pytest.mark.asyncio
async def test_approve_fix_writes_outcome(autofix_with_incident, db_session):
    """End-to-end: approve_fix writes a fix_outcomes row."""
    svc, build = autofix_with_incident
    iid = await build(incident_id="INC-E2E-APPROVE")

    # Stub the parts of approve_fix that reach outside the transaction.
    with patch("src.services.incident_service.IncidentService") as IncSvc:
        IncSvc.return_value.get_incident = AsyncMock(return_value={
            "incident_id": iid,
            "service_name": "payment-api",
            "file_path": "Charge.java",
            "line_number": 88,
            "extra_metadata": json.dumps({
                "auto_fix": {
                    "fix": "--- a\n+++ b\n",
                    "repo_name": "payment-service",
                    "status": "fix_generated",
                    "requires_approval": True,
                },
                "verification": {"passed": True, "reason": "tests_passed"},
            }),
        })

        with patch.object(svc, "_update_auto_fix", new=AsyncMock()):
            result = await svc.approve_fix(iid)

    assert result["status"] == "approved"

    row = (await db_session.execute(
        text("SELECT human_decision FROM fix_outcomes WHERE incident_id = :iid"),
        {"iid": iid},
    )).fetchone()
    assert row is not None
    assert row[0] == "approved"
    
@pytest.mark.asyncio
async def test_reject_fix_writes_outcome(autofix_with_incident, db_session):
    """End-to-end: reject_fix writes a fix_outcomes row with the reason."""
    svc, build = autofix_with_incident
    iid = await build(incident_id="INC-E2E-REJECT")

    with patch("src.services.incident_service.IncidentService") as IncSvc:
        IncSvc.return_value.get_incident = AsyncMock(return_value={
            "incident_id": iid,
            "service_name": "payment-api",
            "file_path": "Charge.java",
            "line_number": 88,
            "extra_metadata": json.dumps({
                "auto_fix": {
                    "fix": "--- a\n+++ b\n",
                    "repo_name": "payment-service",
                    "status": "fix_generated",
                    "requires_approval": True,
                },
                "verification": {"passed": True, "reason": "tests_passed"},
            }),
        })

        with patch.object(svc, "_update_auto_fix", new=AsyncMock()):
            result = await svc.reject_fix(iid, reason="wrong approach")

    assert result["status"] == "rejected"

    row = (await db_session.execute(
        text("""SELECT human_decision, human_reason
                FROM fix_outcomes WHERE incident_id = :iid"""),
        {"iid": iid},
    )).fetchone()
    assert row is not None
    assert row[0] == "rejected"
    assert row[1] == "wrong approach"

# ---------------------------------------------------------------------------
# repo_name targeting in approve_fix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_fix_uses_snapshotted_repo_name(autofix_with_incident):
    """
    auto_fix.repo_name is what generate_fix wrote. It's what
    create_pr receives — no hardcoded 'fastapi'.
    """
    svc, build = autofix_with_incident
    iid = await build(incident_id="INC-REPO-1")

    captured = {}

    async def fake_create_pr(**kwargs):
        captured.update(kwargs)
        return {"mode": "read_only", "status": "skipped", "fix_preview": ""}

    with patch("src.services.incident_service.IncidentService") as IncSvc, \
         patch.object(svc, "_update_auto_fix", new=AsyncMock()), \
         patch.object(svc, "_record_outcome", new=AsyncMock()), \
         patch.object(svc, "create_pr", side_effect=fake_create_pr):
        IncSvc.return_value.get_incident = AsyncMock(return_value={
            "incident_id": iid,
            "service_name": "payment-api",
            "file_path": "Charge.java",
            "line_number": 88,
            "extra_metadata": json.dumps({
                "auto_fix": {
                    "fix": "diff",
                    "repo_name": "payment-service",
                    "status": "fix_generated",
                    "requires_approval": True,
                },
            }),
        })

        await svc.approve_fix(iid)

    assert captured["repo_name"] == "payment-service"


@pytest.mark.asyncio
async def test_approve_fix_refuses_without_repo_name(autofix_with_incident):
    """
    No repo_name snapshot → hard error, no create_pr call, no PR
    targeted at 'fastapi'. The failure is explicit, not silent.
    """
    svc, build = autofix_with_incident
    iid = await build(incident_id="INC-REPO-2")

    create_pr_calls = []

    async def fake_create_pr(**kwargs):
        create_pr_calls.append(kwargs)
        return {"mode": "read_only", "status": "skipped", "fix_preview": ""}

    with patch("src.services.incident_service.IncidentService") as IncSvc, \
         patch.object(svc, "_update_auto_fix", new=AsyncMock()), \
         patch.object(svc, "_record_outcome", new=AsyncMock()), \
         patch.object(svc, "create_pr", side_effect=fake_create_pr):
        IncSvc.return_value.get_incident = AsyncMock(return_value={
            "incident_id": iid,
            "service_name": "payment-api",
            "file_path": "Charge.java",
            "line_number": 88,
            "extra_metadata": json.dumps({
                "auto_fix": {
                    "fix": "diff",
                    # No repo_name — simulating an older snapshot.
                    "status": "fix_generated",
                    "requires_approval": True,
                },
            }),
        })

        result = await svc.approve_fix(iid)

    assert result.get("error")
    assert "repo_name" in result["error"].lower()
    assert create_pr_calls == [], "create_pr must not be called without a repo_name"


@pytest.mark.asyncio
async def test_approve_fix_still_rejects_missing_incident(autofix_with_incident):
    """
    Sanity: the existing 'incident not found' path is unchanged.
    """
    svc, _ = autofix_with_incident

    with patch("src.services.incident_service.IncidentService") as IncSvc:
        IncSvc.return_value.get_incident = AsyncMock(return_value=None)
        result = await svc.approve_fix("INC-NOPE")

    assert result.get("error") == "Incident not found"

# ---------------------------------------------------------------------------
# _extract_diff — turning LLM output into a git-apply-compatible diff
# ---------------------------------------------------------------------------

def test_extract_diff_passthrough_bare_diff():
    """A raw unified diff comes back unchanged (trailing whitespace stripped)."""
    from src.services.autofix_service import AutoFixService

    raw = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n"
    assert AutoFixService._extract_diff(raw) == raw.rstrip()


def test_extract_diff_from_markdown_fence():
    """```diff ... ``` block is unwrapped."""
    from src.services.autofix_service import AutoFixService

    raw = (
        "Here's the fix:\n\n"
        "```diff\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "```\n\n"
        "This change adds a null check.\n"
    )
    extracted = AutoFixService._extract_diff(raw)
    assert extracted.startswith("--- a/x.py")
    assert extracted.endswith("+new")
    assert "Here's the fix" not in extracted
    assert "```" not in extracted
    assert "This change adds" not in extracted


def test_extract_diff_from_bare_fence():
    """``` ... ``` without a language tag works the same way."""
    from src.services.autofix_service import AutoFixService

    raw = "```\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n```\n"
    extracted = AutoFixService._extract_diff(raw)
    assert extracted.startswith("--- a/x.py")
    assert "```" not in extracted


def test_extract_diff_from_prose_wrapped():
    """Prose before the diff without a fence — take from the first --- line."""
    from src.services.autofix_service import AutoFixService

    raw = (
        "I'd suggest this change.\n\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    extracted = AutoFixService._extract_diff(raw)
    assert extracted.startswith("--- a/x.py")
    assert "I'd suggest" not in extracted


def test_extract_diff_no_diff_returns_raw():
    """No diff present — return as-is so the verifier rejects it."""
    from src.services.autofix_service import AutoFixService

    raw = "I cannot fix this issue without more context."
    assert AutoFixService._extract_diff(raw) == raw


def test_extract_diff_handles_empty_string():
    from src.services.autofix_service import AutoFixService
    assert AutoFixService._extract_diff("") == ""
    assert AutoFixService._extract_diff(None) is None


# ---------------------------------------------------------------------------
# _diff_looks_valid — structural pre-check before the verifier
# ---------------------------------------------------------------------------

def test_diff_valid_full_hunk_header():
    from src.services.autofix_service import AutoFixService

    diff = (
        "--- a/x.py\n+++ b/x.py\n"
        "@@ -42,6 +42,7 @@\n"
        " context\n"
        "-old\n"
        "+new\n"
        " context\n"
    )
    assert AutoFixService._diff_looks_valid(diff) is True


def test_diff_valid_hunk_header_without_counts():
    from src.services.autofix_service import AutoFixService

    diff = "--- a/x.py\n+++ b/x.py\n@@ -42 +42 @@\n-old\n+new\n"
    assert AutoFixService._diff_looks_valid(diff) is True


def test_diff_invalid_bare_hunk_marker():
    """The failure mode from the end-to-end run."""
    from src.services.autofix_service import AutoFixService

    diff = (
        "--- a/x.py\n+++ b/x.py\n"
        "@@\n"
        "-old\n"
        "+new\n"
    )
    assert AutoFixService._diff_looks_valid(diff) is False


def test_diff_invalid_no_file_markers():
    from src.services.autofix_service import AutoFixService

    diff = "@@ -1,1 +1,1 @@\n-old\n+new\n"
    assert AutoFixService._diff_looks_valid(diff) is False


def test_diff_invalid_empty_or_truncated():
    from src.services.autofix_service import AutoFixService

    assert AutoFixService._diff_looks_valid("") is False
    assert AutoFixService._diff_looks_valid("--- a/x.py\n") is False
    assert AutoFixService._diff_looks_valid("short") is False
