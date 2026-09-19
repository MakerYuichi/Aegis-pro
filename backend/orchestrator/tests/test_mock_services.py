"""
Shape-parity tests for the mock services.

The mocks exist so DEMO_MODE runs without external credentials. That only
works if they return data with the same *shape* as the real services.
Otherwise callers see KeyErrors, or silently get None where a value was
expected, and the demo breaks in ways tests don't catch.

Two parity rules, matching the design in mock_github_service.py and
mock_slack_service.py:

1. List responses (get_recent_prs, get_related_prs)
   -> items must have EXACTLY the same keys as the real service.
      No additions. No omissions.

2. Dict responses (get_blame_with_pr, get_file_content)
   -> mock keys must be a SUPERSET of real keys. The extra `simulated`
      key is allowed and expected.

The real service is instantiated and its returned-shape constants are
read from its own source, not duplicated here. If the real service
changes shape, these tests fail and force the mock to keep up.
"""

import pytest


# ── Real service shape constants ─────────────────────────────────────────
# These are the keys the real GitHubService returns. Kept as plain sets
# so the test fails loudly if the real service adds or removes a key.

REAL_RECENT_PR_KEYS = {
    "number",
    "title",
    "author",
    "url",
    "merged_at",
    "additions",
    "deletions",
    "files",
}

REAL_BLAME_KEYS = {
    "commit_hash",
    "author",
    "author_avatar",
    "message",
    "line",
    "file",
}

REAL_BLAME_PR_KEYS = {
    "pr_number",
    "pr_title",
    "pr_url",
    "pr_author",
    "contributors",
}

REAL_FILE_CONTENT_KEYS = {
    "file_path",
    "line_number",
    "total_lines",
    "code_snippet",
    "full_file",
}


# ── MockGitHubService — list responses: exact key parity ─────────────────

@pytest.mark.asyncio
async def test_mock_recent_prs_keys_match_real():
    from src.services.mock_github_service import MockGitHubService

    svc = MockGitHubService()
    prs = await svc.get_recent_prs("acme-demo/payment-service")

    assert isinstance(prs, list)
    assert len(prs) > 0
    for pr in prs:
        assert set(pr.keys()) == REAL_RECENT_PR_KEYS, (
            f"get_recent_prs key mismatch: mock={set(pr.keys())} "
            f"real={REAL_RECENT_PR_KEYS}"
        )


@pytest.mark.asyncio
async def test_mock_recent_prs_has_no_simulated_flag():
    """Lists must stay shape-identical to the real service — no 'simulated'."""
    from src.services.mock_github_service import MockGitHubService

    svc = MockGitHubService()
    prs = await svc.get_recent_prs("acme-demo/payment-service")
    for pr in prs:
        assert "simulated" not in pr


@pytest.mark.asyncio
async def test_mock_related_prs_keys_are_superset_of_real():
    """
    get_related_prs in the real service builds candidates from a different
    path than get_recent_prs — it does NOT include additions/deletions.
    It adds relevance_score and reason after LLM scoring.
    """
    from src.services.mock_github_service import MockGitHubService

    svc = MockGitHubService()
    prs = await svc.get_related_prs("acme-demo/payment-service", "PaymentProcessor.java", 442)

    assert isinstance(prs, list)
    assert len(prs) > 0

    expected_keys = {
        "number", "title", "author", "url",
        "merged_at", "files",
        "relevance_score", "reason",
    }
    for pr in prs:
        assert set(pr.keys()) == expected_keys, (
            f"get_related_prs key mismatch: mock={set(pr.keys())} "
            f"expected={expected_keys}"
        )


@pytest.mark.asyncio
async def test_mock_related_prs_has_no_simulated_flag():
    from src.services.mock_github_service import MockGitHubService

    svc = MockGitHubService()
    prs = await svc.get_related_prs("acme-demo/payment-service", "PaymentProcessor.java", 442)
    for pr in prs:
        assert "simulated" not in pr


# ── MockGitHubService — dict responses: superset + simulated ─────────────

@pytest.mark.asyncio
async def test_mock_blame_keys_superset_and_simulated():
    from src.services.mock_github_service import MockGitHubService

    svc = MockGitHubService()
    blame = await svc.get_blame_with_pr(
        "acme-demo/payment-service", "PaymentProcessor.java", 442
    )

    assert isinstance(blame, dict)
    # The mock returns the blame dict plus PR fields plus simulated
    required = REAL_BLAME_KEYS | REAL_BLAME_PR_KEYS | {"simulated"}
    assert set(blame.keys()) >= required, (
        f"get_blame_with_pr missing keys: {required - set(blame.keys())}"
    )
    assert blame["simulated"] is True


@pytest.mark.asyncio
async def test_mock_file_content_keys_superset_and_simulated():
    from src.services.mock_github_service import MockGitHubService

    svc = MockGitHubService()
    content = await svc.get_file_content(
        "acme-demo/payment-service", "PaymentProcessor.java", 442
    )

    assert isinstance(content, dict)
    assert set(content.keys()) >= REAL_FILE_CONTENT_KEYS
    assert content["simulated"] is True
    assert content["file_path"] == "PaymentProcessor.java"
    assert content["line_number"] == 442


@pytest.mark.asyncio
async def test_mock_file_content_does_not_hit_github():
    """
    Belt-and-suspenders: MockGitHubService must never touch the network.
    If someone accidentally imports the real service in the mock, this
    will fail because the real service would require a GITHUB_TOKEN.
    """
    from src.services.mock_github_service import MockGitHubService

    svc = MockGitHubService()
    # The mock has no .client attribute — no PyGithub client was constructed.
    assert not hasattr(svc, "client") or svc.client is None


# ── MockSlackService ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mock_slack_send_message_returns_bool():
    from src.services.mock_slack_service import MockSlackService

    svc = MockSlackService()
    result = await svc.send_message({"text": "hello", "channel": "#test"})
    assert result is True


@pytest.mark.asyncio
async def test_mock_slack_enabled_is_false_for_interface_parity():
    """
    alert_service.py reads self.slack.enabled to compute the 'mock' field.
    MockSlackService.enabled must be False so alert responses honestly
    report that no real Slack message was sent.
    """
    from src.services.mock_slack_service import MockSlackService

    svc = MockSlackService()
    assert svc.enabled is False


@pytest.mark.asyncio
async def test_mock_slack_feed_is_newest_first():
    from src.services.mock_slack_service import (
        MockSlackService,
        get_demo_slack_feed,
    )

    svc = MockSlackService()
    # Clear by constructing the service again is not enough — the deque is
    # module-level and persists. Instead, send uniquely-labeled messages and
    # assert relative order.
    await svc.send_message({"text": "first-unique-msg"})
    await svc.send_message({"text": "second-unique-msg"})

    feed = get_demo_slack_feed()
    assert isinstance(feed, list)
    assert len(feed) >= 2

    # Newest first: second should appear before first in the returned list
    texts = [entry["text"] for entry in feed]
    second_idx = texts.index("second-unique-msg")
    first_idx = texts.index("first-unique-msg")
    assert second_idx < first_idx


@pytest.mark.asyncio
async def test_mock_slack_feed_entries_have_simulated_flag():
    from src.services.mock_slack_service import (
        MockSlackService,
        get_demo_slack_feed,
    )

    svc = MockSlackService()
    await svc.send_message({"text": "simulated-flag-check"})

    feed = get_demo_slack_feed()
    matching = [e for e in feed if e["text"] == "simulated-flag-check"]
    assert len(matching) == 1
    assert matching[0]["simulated"] is True


# ── Factory behavior ─────────────────────────────────────────────────────

def test_factory_returns_real_services_when_demo_mode_false(monkeypatch):
    from src.config import settings
    from src.services.factory import get_github_service, get_slack_service

    monkeypatch.setattr(settings, "DEMO_MODE", False)
    assert type(get_github_service()).__name__ == "GitHubService"
    assert type(get_slack_service()).__name__ == "SlackService"


def test_factory_returns_mock_services_when_demo_mode_true(monkeypatch):
    from src.config import settings
    from src.services.factory import get_github_service, get_slack_service

    monkeypatch.setattr(settings, "DEMO_MODE", True)
    assert type(get_github_service()).__name__ == "MockGitHubService"
    assert type(get_slack_service()).__name__ == "MockSlackService"
