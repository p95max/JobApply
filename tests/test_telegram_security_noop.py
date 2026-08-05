from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.telegram_bot.config import TelegramConfig
from apps.telegram_bot.handlers import handle_update
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


@pytest.mark.django_db
def test_unlinked_user_gets_safe_instruction_for_telegram_connection():
    class Client:
        def __init__(self):
            self.calls = []

        def send_message(self, chat_id, text, *, reply_markup=None):
            self.calls.append((chat_id, text, reply_markup))

    client = Client()
    update = {
        "message": {
            "text": "/start",
            "chat": {"id": 999, "type": "private"},
            "from": {"id": 999},
        }
    }

    handle_update(update, client, _config())

    assert client.calls == [
        (999, "To connect Telegram, generate a one-time code in JobApply Settings → Telegram and send /link <code> here.", None)
    ]


@pytest.mark.django_db
def test_linked_user_is_allowed_and_receives_only_their_gmail_summary(monkeypatch):
    user = get_user_model().objects.create_user("telegram-user", email="telegram-user@example.com")
    UserProfile.objects.create(
        user=user,
        google_data_access_consent=True,
        consent_accepted_at=timezone.now(),
        telegram_user_id=999,
        telegram_chat_id=999,
        telegram_linked_at=timezone.now(),
    )
    captured = []

    class Client:
        def send_message(self, chat_id, text, *, reply_markup=None):
            assert chat_id == 999
            assert "No pending proposals" in text

    monkeypatch.setattr(
        "apps.telegram_bot.handlers.get_gmail_summary",
        lambda email: (captured.append(email) or (0, [])),
    )
    update = {
        "message": {
            "text": "/gmail",
            "chat": {"id": 999, "type": "private"},
            "from": {"id": 999},
        }
    }

    assert is_update_allowed(update, _config()) is True
    handle_update(update, Client(), _config())
    assert captured == [user.email]


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
