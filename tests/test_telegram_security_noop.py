from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.telegram_bot.config import TelegramConfig
from apps.telegram_bot.permissions import is_update_allowed


def _config(**overrides):
    values = {
        "enabled": True,
        "token": "test-token",
        "default_chat_id": 100,
        "allowed_chat_ids": frozenset({100}),
        "allowed_user_ids": frozenset({200}),
        "owner_email": "owner@example.com",
        "environment_label": "TEST",
        "notifications_enabled": True,
    }
    values.update(overrides)
    return TelegramConfig(**values)


@pytest.mark.django_db
def test_unauthorized_chat_id_is_rejected():
    update = {
        "message": {
            "chat": {"id": 999, "type": "private"},
            "from": {"id": 200},
        }
    }

    assert is_update_allowed(update, _config()) is False


def test_disabled_bot_is_noop(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_ENABLED", "0")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_OWNER_EMAIL", raising=False)
    stdout = StringIO()

    call_command("run_telegram_bot", stdout=stdout)

    assert "Telegram Bot is disabled." in stdout.getvalue()


def test_enabled_bot_requires_configuration(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_ENABLED", "1")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_OWNER_EMAIL", raising=False)

    with pytest.raises(CommandError) as error:
        call_command("run_telegram_bot")

    message = str(error.value)
    assert "TELEGRAM_BOT_TOKEN" in message
    assert "TELEGRAM_ALLOWED_CHAT_IDS" in message
    assert "TELEGRAM_ALLOWED_USER_IDS" in message
    assert "TELEGRAM_OWNER_EMAIL" in message
    assert "test-token" not in message
