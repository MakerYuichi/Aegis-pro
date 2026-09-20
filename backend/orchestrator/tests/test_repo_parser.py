import pytest
from src.demo.repo_parser import parse_repo_input, supported_shapes


# ── Accepted shapes ────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected_org,expected_repo", [
    ("https://github.com/uber/ride-dispatch", "uber", "ride-dispatch"),
    ("https://github.com/uber/ride-dispatch.git", "uber", "ride-dispatch"),
    ("git@github.com:uber/ride-dispatch.git", "uber", "ride-dispatch"),
    ("github.com/uber/ride-dispatch", "uber", "ride-dispatch"),
    ("uber/ride-dispatch", "uber", "ride-dispatch"),
    ("https://gitlab.com/group/project", "group", "project"),
    ("https://bitbucket.org/team/repo", "team", "repo"),
])
def test_accepted_shapes(raw, expected_org, expected_repo):
    result = parse_repo_input(raw)
    assert result.ok is True, f"failed with {result.reason}: {result.detail}"
    assert result.org == expected_org
    assert result.repo == expected_repo
    assert result.host in ("github.com", "gitlab.com", "bitbucket.org")


def test_supported_shapes_returns_seven():
    assert len(supported_shapes()) == 7


# ── Error reasons ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected_reason", [
    ("", "empty"),
    ("   ", "empty"),
    (None, "empty"),
    ("justrepo", "too_short"),
    ("has spaces in it", "malformed"),
    ("gitea.com/org/repo", "unsupported_host"),
    ("https://example.com/org/repo", "unsupported_host"),
    ("https://github.com/onlyorg", "missing_repo"),
    ("https://github.com/onlyorg/", "missing_repo"),
])
def test_error_reasons(raw, expected_reason):
    result = parse_repo_input(raw)
    assert result.ok is False
    assert result.reason == expected_reason
    assert result.detail  # must be a human-readable string


# ── Language inference ─────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("github.com/acme/payment-service", "Java"),
    ("github.com/acme/py-worker", "Python"),
    ("github.com/acme/user-python-api", "Python"),
    ("github.com/acme/go-gateway", "Go"),
    ("github.com/acme/golang-agent", "Go"),
    ("github.com/acme/node-proxy", "Node"),
    ("github.com/acme/web-ts", "Node"),
    ("github.com/acme/rust-daemon", "Rust"),
])
def test_language_inference(raw, expected):
    result = parse_repo_input(raw)
    assert result.ok, result.detail
    assert result.language_hint == expected


def test_unknown_language_defaults_to_java():
    result = parse_repo_input("github.com/acme/some-random-service")
    assert result.ok
    assert result.language_hint == "Java"


# ── Determinism ────────────────────────────────────────────────────────

def test_same_input_same_output():
    a = parse_repo_input("github.com/uber/ride-dispatch")
    b = parse_repo_input("github.com/uber/ride-dispatch")
    assert a == b
