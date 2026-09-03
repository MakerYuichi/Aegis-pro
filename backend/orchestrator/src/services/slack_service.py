from src.config import settings
from loguru import logger
import httpx

class SlackService:
    def __init__(self):
        self.webhook_url = settings.SLACK_WEBHOOK_URL
        self.bot_token = settings.SLACK_BOT_TOKEN
        self.enabled = bool(self.webhook_url or self.bot_token)
        logger.info(f"✅ SlackService initialized (enabled: {self.enabled})")
    
    async def send_message(self, message: dict) -> bool:
        """Send a message to Slack"""
        if not self.enabled:
            logger.info(f"💬 [MOCK SLACK] Message: {message.get('text', '')[:50]}...")
            return True
        
        try:
            async with httpx.AsyncClient() as client:
                if self.webhook_url:
                    response = await client.post(self.webhook_url, json=message)
                else:
                    url = "https://slack.com/api/chat.postMessage"
                    headers = {"Authorization": f"Bearer {self.bot_token}"}
                    response = await client.post(url, headers=headers, json=message)
                
                if response.status_code in [200, 201]:
                    logger.info("✅ Slack message sent")
                    return True
                else:
                    logger.error(f"Slack error: {response.status_code} - {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Slack error: {e}")
            return False
