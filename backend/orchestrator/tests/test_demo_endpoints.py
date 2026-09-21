"""
Tests for the demo endpoints. All GitHub and LLM calls are mocked —
no network calls in the suite.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from src.config import settings
from src.demo.endpoints import router as demo_router
from src.demo.risk_analyzer_llm import RiskFinding
from src.demo.file_selector import FileCandidate
from src.demo.github_fetcher import (
    GitHubRepoNotFoundError,
    GitHubRateLimitError,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(demo_router)
    return app


@pytest.fixture
def client_demo_on(monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    return TestClient(_make_app())


@pytest.fixture
def client_demo_off(monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    return TestClient(_make_app())


@pytest.fixture(autouse=True)
def _no_try_cap(monkeypatch):
    """By default, the try cap says 'no tries used yet'."""
    async def _zero(_sid):
        return 0
    monkeypatch.setattr("src.demo.endpoints.count_successful_tries", _zero)


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """record_session is a no-op in tests."""
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr("src.demo.endpoints.record_session", _noop)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """The Redis rate limiter always allows."""
    async def _allow(_sid):
        return None
    monkeypatch.setattr("src.demo.endpoints._check_rate_limit", _allow)


# ── DEMO_MODE=false → 404 on every route ────────────────────────────────

def test_default_404_when_demo_off(client_demo_off):
    assert client_demo_off.get("/api/v1/demo/default").status_code == 404


def test_generate_404_when_demo_off(client_demo_off):
    r = client_demo_off.post("/api/v1/demo/generate", json={"repo_url": "github.com/a/b"})
    assert r.status_code == 404


def test_reset_404_when_demo_off(client_demo_off):
    assert client_demo_off.post("/api/v1/demo/reset").status_code == 404


# ── DEMO_MODE=true → working routes ─────────────────────────────────────

def test_default_returns_aegis_incident(client_demo_on):
    r = client_demo_on.get("/api/v1/demo/default")
    assert r.status_code == 200
    data = r.json()
    assert data["incident_id"] == "INC-DEMO-AEGIS-0001"
    assert data["extra_metadata"]["demo_default"] is True
    assert data["extra_metadata"]["simulated"] is True


def test_generate_empty_url_returns_error_payload(client_demo_on):
    r = client_demo_on.post("/api/v1/demo/generate", json={"repo_url": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["reason"] == "empty"
    assert "supported_shapes" in body
    assert len(body["supported_shapes"]) == 7


def test_generate_malformed_url_returns_error_payload(client_demo_on):
    r = client_demo_on.post(
        "/api/v1/demo/generate", json={"repo_url": "gitea.com/org/repo"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["reason"] == "unsupported_host"


def test_reset_clears_session(client_demo_on):
    r = client_demo_on.post("/api/v1/demo/reset")
    assert r.status_code == 200
    assert r.json()["status"] == "reset"


# ── Try cap ─────────────────────────────────────────────────────────────

def test_signup_required_when_tries_exhausted(client_demo_on, monkeypatch):
    async def _at_cap(_sid):
        return 3
    monkeypatch.setattr("src.demo.endpoints.count_successful_tries", _at_cap)

    r = client_demo_on.post(
        "/api/v1/demo/generate", json={"repo_url": "github.com/uber/ride-dispatch"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["signup_required"] is True
    assert body["tries_remaining"] == 0


def test_successful_generate_reports_tries_remaining(client_demo_on, monkeypatch):
    async def _one(_sid):
        return 1
    monkeypatch.setattr("src.demo.endpoints.count_successful_tries", _one)

    with _mock_full_pipeline():
        r = client_demo_on.post(
            "/api/v1/demo/generate",
            json={"repo_url": "github.com/uber/ride-dispatch"},
        )
    assert r.status_code == 200
    assert r.json()["meta"]["tries_remaining"] == 1


# ── Fetch failures ──────────────────────────────────────────────────────

def test_not_found_when_github_404(client_demo_on):
    with patch(
        "src.demo.endpoints.github_fetcher.fetch_repo_metadata",
        new=AsyncMock(side_effect=GitHubRepoNotFoundError("nope")),
    ):
        r = client_demo_on.post(
            "/api/v1/demo/generate",
            json={"repo_url": "github.com/nope/nope"},
        )
    assert r.status_code == 200
    assert r.json()["reason"] == "not_found"


def test_rate_limited_when_github_403(client_demo_on):
    with patch(
        "src.demo.endpoints.github_fetcher.fetch_repo_metadata",
        new=AsyncMock(side_effect=GitHubRateLimitError()),
    ):
        r = client_demo_on.post(
            "/api/v1/demo/generate",
            json={"repo_url": "github.com/uber/ride-dispatch"},
        )
    assert r.status_code == 200
    assert r.json()["reason"] == "rate_limited"


# ── Selector outcomes ───────────────────────────────────────────────────

def test_empty_repo_returns_empty_repo_error(client_demo_on):
    with _mock_metadata_and_tree(tree=[]):
        with patch(
            "src.demo.endpoints.select_target_files",
            return_value=[],
        ):
            r = client_demo_on.post(
                "/api/v1/demo/generate",
                json={"repo_url": "github.com/uber/empty-repo"},
            )
    assert r.status_code == 200
    assert r.json()["reason"] == "empty_repo"


def test_fallback_confidence_returns_not_code_error(client_demo_on):
    fallback = FileCandidate(
        path="README",
        score=-5.0,
        reasons=["no code extension"],
        confidence="fallback",
    )
    with _mock_metadata_and_tree():
        with patch(
            "src.demo.endpoints.select_target_files",
            return_value=[fallback],
        ):
            r = client_demo_on.post(
                "/api/v1/demo/generate",
                json={"repo_url": "github.com/octocat/Hello-World"},
            )
    assert r.status_code == 200
    assert r.json()["reason"] == "not_code"


# ── Analyzer outcomes ───────────────────────────────────────────────────

def test_no_risk_found_returns_error(client_demo_on):
    good = FileCandidate(
        path="src/handler.py", score=5.0, reasons=[], confidence="high"
    )
    with _mock_full_pipeline(candidate=good):
        # Override the analyzer to return None for this test
        with patch(
            "src.demo.endpoints.analyze_file",
            new=AsyncMock(return_value=None),
        ):
            r = client_demo_on.post(
                "/api/v1/demo/generate",
                json={"repo_url": "github.com/uber/ride-dispatch"},
            )
    assert r.status_code == 200
    assert r.json()["reason"] == "no_risk_found"


# ── Happy path ──────────────────────────────────────────────────────────

def test_generate_valid_url_returns_real_incident(client_demo_on):
    with _mock_full_pipeline():
        r = client_demo_on.post(
            "/api/v1/demo/generate",
            json={"repo_url": "github.com/uber/ride-dispatch"},
        )
    assert r.status_code == 200
    body = r.json()
    assert "incident" in body
    assert "parsed" in body
    assert body["parsed"]["org"] == "uber"
    assert body["parsed"]["repo"] == "ride-dispatch"
    inc = body["incident"]
    assert inc["file_path"] == "src/handlers/upstream.py"
    assert inc["extra_metadata"]["demo_quality"]["real_file"] is True
    assert inc["extra_metadata"]["demo_quality"]["confidence"] == "high"


# ── Helpers ─────────────────────────────────────────────────────────────

def _good_risk():
    return RiskFinding(
        line_number=87,
        line_content="response = client.get(url).json()",
        title="Unguarded JSON parse on upstream response",
        root_cause="No status check before parsing.",
        suggested_fix="Check status_code before parsing.",
        severity="P1",
        exception_type="JSONDecodeError",
        confidence=0.83,
        category="serialization",
        blast_radius_reason="Any caller sees a 500 during an upstream incident.",
        related_lines=[86, 88],
    )


class _mock_metadata_and_tree:
    """Context manager that mocks fetch_repo_metadata and fetch_tree."""

    def __init__(self, tree=None):
        self.tree = tree if tree is not None else [
            {"path": "src/handlers/upstream.py", "type": "blob", "size": 3000}
        ]

    def __enter__(self):
        self._meta_patch = patch(
            "src.demo.endpoints.github_fetcher.fetch_repo_metadata",
            new=AsyncMock(return_value={
                "full_name": "uber/ride-dispatch",
                "default_branch": "main",
                "language": "Python",
            }),
        )
        self._tree_patch = patch(
            "src.demo.endpoints.github_fetcher.fetch_tree",
            new=AsyncMock(return_value=self.tree),
        )
        self._meta_patch.start()
        self._tree_patch.start()
        return self

    def __exit__(self, *args):
        self._tree_patch.stop()
        self._meta_patch.stop()


def _mock_full_pipeline(candidate=None, risk=None):
    """Mock the full happy-path pipeline from fetch through analyze."""
    if candidate is None:
        candidate = FileCandidate(
            path="src/handlers/upstream.py",
            score=5.0,
            reasons=[],
            confidence="high",
        )
    if risk is None:
        risk = _good_risk()

    class _ctx:
        def __enter__(self):
            self._patches = [
                patch(
                    "src.demo.endpoints.github_fetcher.fetch_repo_metadata",
                    new=AsyncMock(return_value={
                        "full_name": "uber/ride-dispatch",
                        "default_branch": "main",
                        "language": "Python",
                    }),
                ),
                patch(
                    "src.demo.endpoints.github_fetcher.fetch_tree",
                    new=AsyncMock(return_value=[
                        {"path": "src/handlers/upstream.py", "type": "blob", "size": 3000}
                    ]),
                ),
                patch(
                    "src.demo.endpoints.select_target_files",
                    return_value=[candidate],
                ),
                patch(
                    "src.demo.endpoints.github_fetcher.fetch_file_content",
                    new=AsyncMock(return_value={
                        "path": candidate.path,
                        "content": "def handler():\n    response = client.get(url).json()\n",
                        "size": 55,
                    }),
                ),
                patch(
                    "src.demo.endpoints.github_fetcher.fetch_file_commits",
                    new=AsyncMock(return_value=[
                        {"sha": "a3f9d21c", "author": "alice",
                         "message": "refactor", "committed_at": "2026-09-14T18:32:00Z"}
                    ]),
                ),
                patch(
                    "src.demo.endpoints.github_fetcher.fetch_contributors",
                    new=AsyncMock(return_value=[
                        {"username": "alice", "avatar_url": None,
                         "contributions": 500, "url": None}
                    ]),
                ),
                patch(
                    "src.demo.endpoints.github_fetcher.fetch_recent_prs",
                    new=AsyncMock(return_value=[
                        {"number": 127, "title": "refactor", "author": "alice",
                         "url": "https://github.com/uber/ride-dispatch/pull/127",
                         "merged_at": "2026-09-14T18:32:00Z", "state": "closed"}
                    ]),
                ),
                patch(
                    "src.demo.endpoints.analyze_file",
                    new=AsyncMock(return_value=risk),
                ),
            ]
            for p in self._patches:
                p.start()
            return self

        def __exit__(self, *args):
            for p in self._patches:
                p.stop()

    return _ctx()


def test_successful_generate_returns_timings(client_demo_on, monkeypatch):
    async def _one(_sid):
        return 1
    monkeypatch.setattr("src.demo.endpoints.count_successful_tries", _one)

    with _mock_full_pipeline():
        r = client_demo_on.post(
            "/api/v1/demo/generate",
            json={"repo_url": "github.com/uber/ride-dispatch"},
        )
    assert r.status_code == 200
    timings = r.json()["meta"]["timings"]
    assert "total_ms" in timings
    assert "analyze_ms" in timings
    assert isinstance(timings["total_ms"], int)
