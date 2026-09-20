import json
import pytest
from src.demo.repo_parser import parse_repo_input
from src.demo.incident_generator import generate_incident


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


@pytest.mark.parametrize("org,repo,language,markers", [
    # Java — either scenario is fine; both use JVM stack trace syntax
    ("acme", "payment-service", "Java", ["Exception", "\tat com."]),
    # Python — Traceback header + File/line syntax
    ("acme", "py-worker", "Python", ["Traceback", "File", "line"]),
    # Go — panic header + goroutine
    ("acme", "go-gateway", "Go", ["panic:", "goroutine"]),
    # Node — TypeError + "at handleRequest"
    ("acme", "node-proxy", "Node", ["TypeError", "at handleRequest"]),
    # Rust — panicked + Option::unwrap
    ("acme", "rust-daemon", "Rust", ["panicked", "Option::unwrap"]),
])
def test_stack_trace_matches_inferred_language(org, repo, language, markers):
    parsed = _parsed(org, repo)
    inc = generate_incident(parsed, seed=3)
    assert parsed.language_hint == language
    for marker in markers:
        assert marker in inc["stack_trace"], (
            f"missing {marker!r} in stack trace for {language}:\n{inc['stack_trace']}"
        )


def test_blame_author_uses_org_domain():
    parsed = _parsed("uber", "ride-dispatch")
    inc = generate_incident(parsed, seed=5)
    author = inc["extra_metadata"]["github"]["blame"]["author"]
    assert author.endswith("@uber.com"), author


def test_related_prs_url_contains_org_and_repo():
    parsed = _parsed("stripe", "charge-service")
    inc = generate_incident(parsed, seed=11)
    prs = inc["extra_metadata"]["github"]["related_prs"]
    assert len(prs) >= 2
    for pr in prs:
        assert "stripe/charge-service" in pr["url"]


def test_confidence_in_range():
    for seed in (1, 5, 42, 100):
        parsed = _parsed("acme", "payment-service")
        inc = generate_incident(parsed, seed=seed)
        assert 0.70 <= inc["confidence_score"] <= 0.96


def test_failed_parse_result_raises():
    from src.demo.repo_parser import parse_repo_input
    bad = parse_repo_input("gitea.com/org/repo")
    assert bad.ok is False
    with pytest.raises(ValueError):
        generate_incident(bad, seed=1)


def test_output_is_json_serializable():
    parsed = _parsed("uber", "ride-dispatch")
    inc = generate_incident(parsed, seed=9)
    # Must round-trip through json without error, matching what the
    # endpoint will do when it returns the payload.
    assert json.loads(json.dumps(inc)) == inc


def test_determinism_across_two_calls():
    parsed = _parsed("stripe", "charge-service")
    a = generate_incident(parsed, seed=99)
    b = generate_incident(parsed, seed=99)
    assert a == b
