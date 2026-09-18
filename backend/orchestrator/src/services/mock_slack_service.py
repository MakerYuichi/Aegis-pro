"""
Mock Slack service for DEMO_MODE.

Mirrors SlackService's single public method:

    send_message(message: dict) -> bool

Returns True without posting to Slack. Logs the message so demo runs are
observable in the container output. Every call is recorded on an in-memory
feed that the ActivityFeed component can read in DEMO_MODE — the feed lives
in this module so it's process-local and doesn't leak into production.
"""

from collections import deque
from datetime import datetime, timezone
from loguru import logger


# Process-local ring buffer of the last N messages sent during a demo session.
# Not persisted. Cleared on container restart. Bounded to avoid unbounded
# growth if a buyer hammers the demo.
_FEED = deque(maxlen=100)


def get_demo_slack_feed() -> list:
    """
    Return the most recent demo Slack messages, newest first.

    Intended for the ActivityFeed to read in DEMO_MODE. Not used outside
    of DEMO_MODE — the real SlackService posts to Slack instead.
    """
    return list(reversed(_FEED))


class MockSlackService:
    """Deterministic, network-free implementation of SlackService."""

    def __init__(self):
        # Interface parity with SlackService — alert_service.py reads this
        # attribute directly. False because DEMO_MODE is not connected to a
        # real Slack workspace; send_message() still logs and returns True.
        self.enabled = False
        logger.info("🛠️  MockSlackService initialized (DEMO_MODE)")

    async def send_message(self, message: dict) -> bool:
        text = message.get("text", "") if isinstance(message, dict) else str(message)
        preview = text[:80] + ("…" if len(text) > 80 else "")

        logger.info(f"💬 [MOCK SLACK] {preview}")

        _FEED.append(
            {
                "text": text,
                "channel": message.get("channel") if isinstance(message, dict) else None,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "simulated": True,
            }
        )
        return True
