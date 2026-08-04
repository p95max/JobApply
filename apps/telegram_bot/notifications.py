from __future__ import annotations

import logging

from .client import TelegramClient
from .config import TelegramConfig

logger = logging.getLogger(__name__)


def send_notification(text: str, *, config: TelegramConfig | None = None) -> bool:
    config = config or TelegramConfig.from_env()
    if not config.enabled or not config.notifications_enabled or config.default_chat_id is None:
        return False

    client = TelegramClient(config.token)
    try:
        client.send_message(config.default_chat_id, text)
        return True
    except Exception:
        logger.exception("Telegram notification delivery failed")
        return False
    finally:
        client.close()
