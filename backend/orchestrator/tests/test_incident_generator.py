import json
import pytest

from src.demo.repo_parser import parse_repo_input
from src.demo.incident_generator import (
    generate_incident,
    generate_incident_from_analysis,
)
from src.demo.risk_analyzer_llm import RiskFinding


# ── Legacy path tests (unchanged) ────────────────────────────────────────

REQUIRED_TOP_LEVEL_KEYS = {
    "incident_id", "service_name", "severity", "status", "title",
    "description", "stack_trace", "exception_type", "file_path",
    "line_number", "root_cause", "suggested_fix", "rollback_command",
    "confidence_score", "declared_at", "affected_services", "extra_metadata",
}

REQUIRED_METADATA_KEYS = {
    "simulated", "demo_default", "rag_context_used",
    "github", "code_context", "auto_fix",
}


def _parsed(org, repo):
    r = parse_repo_input(f"github.com/{org}/{repo}")
    assert r.ok, r.detail
    return r


def test_shape_matches_frontend_incident_type():
    parsed = _parsed("uber", "ride-dispatch")
    inc = generate_incident(parsed, seed=42)
    assert set(inc.keys()) == REQUIRED_TOP_LEVEL_KEYS
    assert set(inc["extra_metadata"].keys()) == REQUIRED_METADATA_KEYS


def test_service_name_is_the_repo_name():
    parsed = _parsed("stripe", "charge-service")
    inc = generate_incident(parsed, seed=1)
    assert inc["service_name"] == "charge-service"


def test_incident_id_is_deterministic():
    parsed = _parsed("uber", "ride-dispatch")
    a = generate_incident(parsed, seed=7)["incident_id"]
    b = generate_incident(parsed, seed=7)["incident_id"]
    assert a == b
    assert a.startswith("INC-DEMO-")


def test_different_seed_produces_different_incident_id():
    parsed = _parsed("uber", "ride-dispatch")
    a = generate_incident(parsed, seed=7)["incident_id"]
    b = generate_incident(parsed, seed=8)["incident_id"]
    assert a != b


def test_output_is_json_serializable():
    parsed = _parsed("uber", "ride-dispatch")
    inc = generate_incident(parsed, seed=9)
    assert json.loads(json.dumps(inc)) == inc


def test_determinism_across_two_calls():
    parsed = _parsed("stripe", "charge-service")
    a = generate_incident(parsed, seed=99)
    b = generate_incident(parsed, seed=99)
    assert a == b


def test_failed_parse_result_raises():
    bad = parse_repo_input("gitea.com/org/repo")
    assert bad.ok is False
    with pytest.raises(ValueError):
        generate_incident(bad, seed=1)


# ── New path: generate_incident_from_analysis ────────────────────────────

def _risk(
    line_number=87,
    line_content="response = client.get(url).json()",
    title="Unguarded JSON parse on upstream response",
    severity="P1",
    confidence=0.83,
):
    return RiskFinding(
        line_number=line_number,
        line_content=line_content,
        title=title,
        root_cause=(
            "The response body is parsed without checking status_code. "
            "A non-JSON 4xx/5xx body raises here."
        ),
        suggested_fix=(
            "Check response.status_code before parsing, or wrap in "
            "try/except and handle the non-JSON case explicitly."
        ),
        severity=severity,
        exception_type="JSONDecodeError",
        confidence=confidence,
        category="serialization",
        blast_radius_reason=(
            "Any caller that invokes this handler will receive a 500 during "
            "an upstream incident, compounding the outage."
        ),
        related_lines=[86, 88],
    )


def _file_content():
    return (
        "def handler(url):\n"
        "    # fetch from upstream\n"
        "    response = client.get(url).json()\n"
        "    return response\n"
    )


def _file_commits():
    return [
        {
            "sha": "a3f9d21c",
            "author": "alice",
            "message": "refactor: simplify response handling",
            "committed_at": "2026-09-14T18:32:00Z",
        }
    ]


def _contributors():
    return [
        {"username": "alice", "avatar_url": None, "contributions": 500, "url": None},
        {"username": "bob", "avatar_url": None, "contributions": 200, "url": None},
    ]


def _related_prs():
    return [
        {
            "number": 127,
            "title": "refactor: simplify response handling",
            "author": "alice",
            "url": "https://github.com/uber/ride-dispatch/pull/127",
            "merged_at": "2026-09-14T18:32:00Z",
            "state": "closed",
        }
    ]


def _repo_meta():
    return {
        "full_name": "uber/ride-dispatch",
        "default_branch": "main",
        "language": "Python",
    }


@pytest.mark.asyncio
async def test_returns_none_when_target_file_is_none():
    inc = await generate_incident_from_analysis(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file=None,
        file_content=_file_content(),
        risk=_risk(),
        related_prs=_related_prs(),
        recent_prs=_related_prs(),
        file_commits=_file_commits(),
        contributors=_contributors(),
    )
    assert inc is None


@pytest.mark.asyncio
async def test_returns_none_when_risk_is_none():
    inc = await generate_incident_from_analysis(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file="src/handlers/upstream.py",
        file_content=_file_content(),
        risk=None,
        related_prs=_related_prs(),
        recent_prs=_related_prs(),
        file_commits=_file_commits(),
        contributors=_contributors(),
    )
    assert inc is None


@pytest.mark.asyncio
async def test_returns_none_when_file_content_is_none():
    inc = await generate_incident_from_analysis(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file="src/handlers/upstream.py",
        file_content=None,
        risk=_risk(),
        related_prs=_related_prs(),
        recent_prs=_related_prs(),
        file_commits=_file_commits(),
        contributors=_contributors(),
    )
    assert inc is None


@pytest.mark.asyncio
async def test_uses_risk_title_and_severity_and_line():
    inc = await generate_incident_from_analysis(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file="src/handlers/upstream.py",
        file_content=_file_content(),
        risk=_risk(line_number=3, title="Custom title", severity="P0"),
        related_prs=_related_prs(),
        recent_prs=_related_prs(),
        file_commits=_file_commits(),
        contributors=_contributors(),
    )
    assert inc is not None
    assert inc["title"] == "Custom title"
    assert inc["severity"] == "P0"
    assert inc["line_number"] == 3
    assert inc["file_path"] == "src/handlers/upstream.py"
    assert inc["exception_type"] == "JSONDecodeError"


@pytest.mark.asyncio
async def test_stack_trace_contains_real_line_and_path():
    inc = await generate_incident_from_analysis(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file="src/handlers/upstream.py",
        file_content=_file_content(),
        risk=_risk(line_number=3),
        related_prs=_related_prs(),
        recent_prs=_related_prs(),
        file_commits=_file_commits(),
        contributors=_contributors(),
    )
    assert inc is not None
    assert "src/handlers/upstream.py" in inc["stack_trace"]
    assert "response = client.get(url).json()" in inc["stack_trace"]


@pytest.mark.asyncio
async def test_code_context_uses_real_file_content():
    inc = await generate_incident_from_analysis(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file="src/handlers/upstream.py",
        file_content=_file_content(),
        risk=_risk(line_number=3),
        related_prs=_related_prs(),
        recent_prs=_related_prs(),
        file_commits=_file_commits(),
        contributors=_contributors(),
    )
    assert inc is not None
    ctx = inc["extra_metadata"]["code_context"]
    assert ctx["file_path"] == "src/handlers/upstream.py"
    assert ctx["line_number"] == 3
    assert "response = client.get(url).json()" in ctx["code_snippet"]
    assert ctx["simulated"] is False


@pytest.mark.asyncio
async def test_blame_uses_real_commit_and_contributor():
    inc = await generate_incident_from_analysis(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file="src/handlers/upstream.py",
        file_content=_file_content(),
        risk=_risk(),
        related_prs=_related_prs(),
        recent_prs=_related_prs(),
        file_commits=_file_commits(),
        contributors=_contributors(),
    )
    assert inc is not None
    blame = inc["extra_metadata"]["github"]["blame"]
    assert blame["author"] == "alice"
    assert blame["commit_hash"] == "a3f9d21c"
    assert blame["message"] == "refactor: simplify response handling"
    assert blame["contributors"][0]["username"] == "alice"


@pytest.mark.asyncio
async def test_related_prs_uses_real_pr_number_and_url():
    inc = await generate_incident_from_analysis(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file="src/handlers/upstream.py",
        file_content=_file_content(),
        risk=_risk(),
        related_prs=_related_prs(),
        recent_prs=_related_prs(),
        file_commits=_file_commits(),
        contributors=_contributors(),
    )
    assert inc is not None
    prs = inc["extra_metadata"]["github"]["related_prs"]
    assert prs[0]["number"] == 127
    assert "uber/ride-dispatch/pull/127" in prs[0]["url"]


@pytest.mark.asyncio
async def test_demo_quality_block_is_populated():
    inc = await generate_incident_from_analysis(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file="src/handlers/upstream.py",
        file_content=_file_content(),
        risk=_risk(),
        related_prs=_related_prs(),
        recent_prs=_related_prs(),
        file_commits=_file_commits(),
        contributors=_contributors(),
    )
    assert inc is not None
    dq = inc["extra_metadata"]["demo_quality"]
    assert dq["confidence"] == "high"
    assert dq["real_file"] is True
    assert dq["category"] == "serialization"
    assert dq["related_lines"] == [86, 88]


@pytest.mark.asyncio
async def test_deterministic_incident_id_across_two_calls():
    kwargs = dict(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file="src/handlers/upstream.py",
        file_content=_file_content(),
        related_prs=_related_prs(),
        recent_prs=_related_prs(),
        file_commits=_file_commits(),
        contributors=_contributors(),
    )
    a = await generate_incident_from_analysis(risk=_risk(line_number=3), **kwargs)
    b = await generate_incident_from_analysis(risk=_risk(line_number=99), **kwargs)
    assert a is not None and b is not None
    # Same (org, repo, seed) → same incident ID, even if the LLM picked
    # a different line the second time.
    assert a["incident_id"] == b["incident_id"]


@pytest.mark.asyncio
async def test_output_is_json_serializable():
    inc = await generate_incident_from_analysis(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file="src/handlers/upstream.py",
        file_content=_file_content(),
        risk=_risk(),
        related_prs=_related_prs(),
        recent_prs=_related_prs(),
        file_commits=_file_commits(),
        contributors=_contributors(),
    )
    assert inc is not None
    assert json.loads(json.dumps(inc)) == inc


@pytest.mark.asyncio
async def test_handles_empty_commits_and_contributors():
    """No commit history and no contributors — must not crash."""
    inc = await generate_incident_from_analysis(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file="src/handlers/upstream.py",
        file_content=_file_content(),
        risk=_risk(),
        related_prs=[],
        recent_prs=_related_prs(),
        file_commits=[],
        contributors=[],
    )
    assert inc is not None
    blame = inc["extra_metadata"]["github"]["blame"]
    assert blame["author"].endswith("@uber")   # fallback handle
    assert blame["commit_hash"] == "unknown"
    
@pytest.mark.asyncio
async def test_blame_omits_pr_fields_when_no_related_prs():
    """If the file has no associated PR, the blame block must not
    fabricate one."""
    inc = await generate_incident_from_analysis(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file="src/handlers/upstream.py",
        file_content=_file_content(),
        risk=_risk(),
        related_prs=[],
        recent_prs=_related_prs(),
        file_commits=_file_commits(),
        contributors=_contributors(),
    )
    assert inc is not None
    blame = inc["extra_metadata"]["github"]["blame"]
    assert "pr_number" not in blame
    assert "pr_title" not in blame
    assert "pr_url" not in blame
    
@pytest.mark.asyncio
async def test_recent_prs_present_in_metadata():
    inc = await generate_incident_from_analysis(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file="src/handlers/upstream.py",
        file_content=_file_content(),
        risk=_risk(),
        related_prs=_related_prs(),
        recent_prs=[{"number": 999, "title": "Unrelated PR", "author": "a",
                     "url": "u", "merged_at": "2026-09-01T00:00:00Z"}],
        file_commits=_file_commits(),
        contributors=_contributors(),
    )
    assert inc is not None
    gh = inc["extra_metadata"]["github"]
    assert "recent_prs" in gh
    assert len(gh["recent_prs"]) == 1
    assert gh["recent_prs"][0]["number"] == 999
    # related_prs and recent_prs are distinct lists
    assert gh["related_prs"][0]["number"] == 127
    
@pytest.mark.asyncio
async def test_blame_does_not_crash_when_changes_have_no_prs():
    """
    Regression: related_prs may contain commits with no PR attached.
    _make_real_blame must not crash on that shape.
    """
    commits_without_prs = [
        {
            "sha": "aaaa1111",
            "commit_message": "direct push",
            "commit_date": "2026-01-01T00:00:00Z",
            "author": "alice",
            "relevance_score": 0.8,
            "reason": "direct commit",
        },
    ]
    inc = await generate_incident_from_analysis(
        parsed=_parsed("uber", "ride-dispatch"),
        seed=42,
        repo_meta=_repo_meta(),
        target_file="src/handlers/upstream.py",
        file_content=_file_content(),
        risk=_risk(),
        related_prs=commits_without_prs,
        recent_prs=[],
        file_commits=_file_commits(),
        contributors=_contributors(),
    )
    assert inc is not None
    blame = inc["extra_metadata"]["github"]["blame"]
    # No PR fields — the changes list had none.
    assert "pr_number" not in blame
    assert "pr_title" not in blame
