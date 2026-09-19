"""
Service factories.

When DEMO_MODE is True, the factory returns mock implementations that
never touch external networks. When False, the real services are returned.

Imports are done lazily inside each function to avoid circular imports:
GitHubService imports LLMService, LLMService imports the LLM provider
chain, and the chain imports every provider. If the factory imported
GitHubService at module level, importing the factory would drag in the
whole LLM stack.
"""

from src.config import settings
from loguru import logger


def get_github_service():
    """
    Return GitHubService (real) or MockGitHubService (DEMO_MODE).

    Both implement the same four public methods:
        get_recent_prs, get_blame_with_pr, get_related_prs, get_file_content
    Callers must not reach into private methods on either.
    """
    if settings.DEMO_MODE:
        from src.services.mock_github_service import MockGitHubService
        logger.debug("🛠️  Using MockGitHubService (DEMO_MODE=true)")
        return MockGitHubService()

    from src.services.github_service import GitHubService
    return GitHubService()


def get_slack_service():
    """
    Return SlackService (real) or MockSlackService (DEMO_MODE).

    Both implement the same public method:
        send_message(message: dict) -> bool
    """
    if settings.DEMO_MODE:
        from src.services.mock_slack_service import MockSlackService
        logger.debug("🛠️  Using MockSlackService (DEMO_MODE=true)")
        return MockSlackService()

    from src.services.slack_service import SlackService
    return SlackService()
