from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def block_real_telegram_delivery(monkeypatch):
    """Never allow pytest to call the real Telegram Bot API."""
    monkeypatch.setattr(
        "apps.telegram_bot.client.TelegramClient.send_message",
        lambda self, chat_id, text, **kwargs: None,
    )
