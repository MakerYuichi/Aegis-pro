from pathlib import Path

import pytest


def _find_migration_path() -> Path:
    """Resolve the seed SQL path. Raises if not found."""
    filename = "005_seed_demo_incidents.sql"

    # 1. Container path (docker-compose :ro mount)
    container_path = Path(f"/database/migrations/{filename}")
    if container_path.exists():
        return container_path

    # 2. Walk up from the test file looking for database/migrations/<file>
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "database" / "migrations" / filename
        if candidate.exists():
            return candidate

    # 3. Explicit fallback: repo root as inferred from CI's working dir
    #    (helpful error message when the file truly isn't there)
    raise FileNotFoundError(
        f"{filename} not found. Checked:\n"
        f"  - {container_path}\n"
        f"  - walked up from {here} looking for database/migrations/{filename}\n"
        "\nIf you're inside the orchestrator container, verify the "
        "docker-compose volume mount './database:/database:ro' is present. "
        "If you're in CI, ensure the workflow checks out the repo and runs "
        "pytest from the repo root (or that backend/orchestrator is a "
        "subdirectory that has database/ as a sibling)."
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
