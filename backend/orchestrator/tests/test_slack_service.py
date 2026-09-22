"""
Tests for src/services.slack_service.py.

Covers:
  - Initialization with/without credentials
  - send_message: webhook mode, bot token mode, disabled mode
  - Error handling for HTTP failures
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.slack_service import SlackService


@pytest.fixture
def service():
    """SlackService with credentials."""
    with patch("src.services.slack_service.settings") as settings:
        settings.SLACK_WEBHOOK_URL = "https://hooks.slack.com/webhook"
        settings.SLACK_BOT_TOKEN = "xoxb-test"
        
        svc = SlackService()
    return svc


@pytest.fixture
def service_no_creds():
    """SlackService without credentials (disabled)."""
    with patch("src.services.slack_service.settings") as settings:
        settings.SLACK_WEBHOOK_URL = None
        settings.SLACK_BOT_TOKEN = None
        
        svc = SlackService()
    return svc


@pytest.fixture
def service_webhook_only():
    """SlackService with only webhook URL."""
    with patch("src.services.slack_service.settings") as settings:
        settings.SLACK_WEBHOOK_URL = "https://hooks.slack.com/webhook"
        settings.SLACK_BOT_TOKEN = None
        
        svc = SlackService()
    return svc


@pytest.fixture
def service_bot_token_only():
    """SlackService with only bot token."""
    with patch("src.services.slack_service.settings") as settings:
        settings.SLACK_WEBHOOK_URL = None
        settings.SLACK_BOT_TOKEN = "xoxb-test"
        
        svc = SlackService()
    return svc


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def test_init_with_webhook():
    """
    Situation: SLACK_WEBHOOK_URL configured.
    Expected: Service enabled with webhook URL.
    Function: src.services.slack_service.SlackService.__init__
    """
    with patch("src.services.slack_service.settings") as settings:
        settings.SLACK_WEBHOOK_URL = "https://hooks.slack.com/webhook"
        settings.SLACK_BOT_TOKEN = None
        
        svc = SlackService()
        
        assert svc.webhook_url == "https://hooks.slack.com/webhook"
        assert svc.enabled is True


def test_init_with_bot_token():
    """
    Situation: SLACK_BOT_TOKEN configured.
    Expected: Service enabled with bot token.
    Function: src.services.slack_service.SlackService.__init__
    """
    with patch("src.services.slack_service.settings") as settings:
        settings.SLACK_WEBHOOK_URL = None
        settings.SLACK_BOT_TOKEN = "xoxb-test"
        
        svc = SlackService()
        
        assert svc.bot_token == "xoxb-test"
        assert svc.enabled is True


def test_init_without_credentials():
    """
    Situation: No Slack credentials configured.
    Expected: Service disabled.
    Function: src.services.slack_service.SlackService.__init__
    """
    with patch("src.services.slack_service.settings") as settings:
        settings.SLACK_WEBHOOK_URL = None
        settings.SLACK_BOT_TOKEN = None
        
        svc = SlackService()
        
        assert svc.enabled is False


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_message_with_webhook(service_webhook_only):
    """
    Situation: Webhook URL configured.
    Expected: Posts to webhook URL.
    Function: src.services.slack_service.SlackService.send_message
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    
    with patch("src.services.slack_service.httpx.AsyncClient") as client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        client_cls.return_value = mock_client
        
        result = await service_webhook_only.send_message({"text": "test"})
        
        assert result is True
        mock_client.post.assert_awaited_once_with(
            "https://hooks.slack.com/webhook",
            json={"text": "test"}
        )


@pytest.mark.asyncio
async def test_send_message_with_bot_token(service_bot_token_only):
    """
    Situation: Bot token configured.
    Expected: Posts to Slack API with auth header.
    Function: src.services.slack_service.SlackService.send_message
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    
    with patch("src.services.slack_service.httpx.AsyncClient") as client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        client_cls.return_value = mock_client
        
        result = await service_bot_token_only.send_message({"text": "test"})
        
        assert result is True
        mock_client.post.assert_awaited_once()
        call_kwargs = mock_client.post.await_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer xoxb-test"
        # URL is the first positional argument
        call_args = mock_client.post.await_args.args
        assert "slack.com/api/chat.postMessage" in call_args[0]


@pytest.mark.asyncio
async def test_send_message_disabled_logs_mock(service_no_creds):
    """
    Situation: Service disabled (no credentials).
    Expected: Logs mock message, returns True.
    Function: src.services.slack_service.SlackService.send_message
    """
    result = await service_no_creds.send_message({"text": "test message"})
    
    assert result is True


@pytest.mark.asyncio
async def test_send_message_webhook_success(service_webhook_only):
    """
    Situation: Webhook returns 200.
    Expected: Returns True.
    Function: src.services.slack_service.SlackService.send_message
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    
    with patch("src.services.slack_service.httpx.AsyncClient") as client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        client_cls.return_value = mock_client
        
        result = await service_webhook_only.send_message({"text": "test"})
        
        assert result is True


@pytest.mark.asyncio
async def test_send_message_webhook_201(service_webhook_only):
    """
    Situation: Webhook returns 201.
    Expected: Returns True.
    Function: src.services.slack_service.SlackService.send_message
    """
    mock_response = MagicMock()
    mock_response.status_code = 201
    
    with patch("src.services.slack_service.httpx.AsyncClient") as client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        client_cls.return_value = mock_client
        
        result = await service_webhook_only.send_message({"text": "test"})
        
        assert result is True


@pytest.mark.asyncio
async def test_send_message_webhook_error_status(service_webhook_only):
    """
    Situation: Webhook returns error status.
    Expected: Returns False.
    Function: src.services.slack_service.SlackService.send_message
    """
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"
    
    with patch("src.services.slack_service.httpx.AsyncClient") as client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        client_cls.return_value = mock_client
        
        result = await service_webhook_only.send_message({"text": "test"})
        
        assert result is False


@pytest.mark.asyncio
async def test_send_message_http_error(service_webhook_only):
    """
    Situation: HTTP request fails.
    Expected: Returns False.
    Function: src.services.slack_service.SlackService.send_message
    """
    with patch("src.services.slack_service.httpx.AsyncClient") as client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=RuntimeError("network error"))
        client_cls.return_value = mock_client
        
        result = await service_webhook_only.send_message({"text": "test"})
        
        assert result is False


@pytest.mark.asyncio
async def test_send_message_empty_message(service_webhook_only):
    """
    Situation: Empty message dict.
    Expected: Posts empty dict to webhook.
    Function: src.services.slack_service.SlackService.send_message
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    
    with patch("src.services.slack_service.httpx.AsyncClient") as client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        client_cls.return_value = mock_client
        
        result = await service_webhook_only.send_message({})
        
        assert result is True
