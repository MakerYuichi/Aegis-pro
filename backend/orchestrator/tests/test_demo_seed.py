"""
Tests for the demo seed SQL and the startup embedding backfill.

The seed SQL lives at database/migrations/005_seed_demo_incidents.sql in
the repo root. docker-compose mounts ./database into the orchestrator
container at /database (read-only), so the container-relative path is
/database/migrations/005_seed_demo_incidents.sql.

Two environments, one resolution strategy:
  - Inside the container: /app/tests/test_demo_seed.py -> /database
  - On the host:          <repo>/backend/orchestrator/tests/test_demo_seed.py
                          -> <repo>/database

The function below walks up from __file__ and tries each plausible path
until it finds the file. If it can't find it anywhere, the test fails
loudly with a clear message — it does NOT skip. A missing file means the
mount is broken, and we want to know.
"""

from pathlib import Path

import pytest


def _find_migration_path() -> Path:
    """Resolve the seed SQL path. Raises if not found."""
    here = Path(__file__).resolve()

    candidates = [
        # Container: /app/tests/test_demo_seed.py -> /database/migrations
        Path("/database/migrations/005_seed_demo_incidents.sql"),
        # Host: <repo>/backend/orchestrator/tests/... -> <repo>/database/migrations
        here.parents[2] / "database/migrations/005_seed_demo_incidents.sql",
        # Belt-and-suspenders: some layouts put tests/ one level deeper
        here.parents[1] / "database/migrations/005_seed_demo_incidents.sql",
    ]

    for c in candidates:
        if c.exists():
            return c

    raise FileNotFoundError(
        "005_seed_demo_incidents.sql not found. Checked:\n"
        + "\n".join(f"  - {c}" for c in candidates)
        + "\n\nIf you're inside the orchestrator container, verify the "
        "docker-compose volume mount './database:/database:ro' is present."
    )


MIGRATION_PATH = _find_migration_path()

# ── Seed SQL sanity ─────────────────────────────────────────────

def test_seed_sql_exists():
    assert MIGRATION_PATH.exists(), f"Seed SQL missing: {MIGRATION_PATH}"


def test_seed_sql_has_expected_incident_count():
    sql = MIGRATION_PATH.read_text()
    # One INSERT INTO incidents statement, followed by 11 rows.
    # Count the incident_id literals instead of the INSERT keyword.
    incident_ids = [
        line for line in sql.splitlines()
        if line.strip().startswith("'INC-")
    ]
    assert len(incident_ids) == 11, f"expected 11 incidents, found {len(incident_ids)}"


def test_seed_sql_has_no_razorpay_strings():
    """Regression guard for #43 — do not reintroduce branded data."""
    sql = MIGRATION_PATH.read_text().lower()
    for banned in ("razorpay", "@rahul", "@priya ", "@sneha", "@amit", "@shreya",
                   "@ananya", "@arjun", "@kavya", "@raj ", "@vikram", "@manish"):
        assert banned not in sql, f"banned string '{banned}' present in seed SQL"


def test_seed_sql_marks_all_incidents_demo_seed():
    sql = MIGRATION_PATH.read_text()
    assert sql.count('"demo_seed": true') == 11


def test_seed_sql_is_idempotent():
    """Leading DELETE scoped to demo_seed must be present."""
    sql = MIGRATION_PATH.read_text()
    assert "DELETE FROM incidents WHERE extra_metadata->>'demo_seed' = 'true'" in sql


# ── Backfill behavior ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_backfill_is_noop_when_demo_mode_false(monkeypatch):
    from src.config import settings
    from src.demo.seed_backfill import backfill_demo_embeddings

    monkeypatch.setattr(settings, "DEMO_MODE", False)

    class ExplodingRAG:
        async def store_incident(self, *a, **kw):
            raise AssertionError("backfill must not touch RAG when DEMO_MODE=false")

    result = await backfill_demo_embeddings(ExplodingRAG())
    assert result == 0


@pytest.mark.asyncio
async def test_backfill_is_idempotent_when_no_rows(monkeypatch):
    """If the DB has no demo_seed rows without embeddings, backfill returns 0."""
    from src.config import settings
    from src.demo import seed_backfill as mod

    monkeypatch.setattr(settings, "DEMO_MODE", True)

    class FakeResult:
        def fetchall(self):
            return []

    class FakeSession:
        async def execute(self, *a, **kw):
            return FakeResult()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def fake_get_db():
        return FakeSession()

    monkeypatch.setattr(mod, "get_db", fake_get_db)

    calls = []

    class RecordingRAG:
        async def store_incident(self, data):
            calls.append(data)

    result = await mod.backfill_demo_embeddings(RecordingRAG())
    assert result == 0
    assert calls == []
