from __future__ import annotations

import pytest

from apps.telegram_bot.config import TelegramConfig
from apps.telegram_bot.models import TelegramDelivery, TelegramDeliveryStatus
from apps.telegram_bot.notifications import send_notification_once


def _config() -> TelegramConfig:
    return TelegramConfig(
        enabled=True,
        token="token",
        default_chat_id=123,
        allowed_chat_ids=frozenset({123}),
        allowed_user_ids=frozenset({123}),
        owner_email="owner@example.com",
        environment_label="TEST",
        notifications_enabled=True,
    )


@pytest.mark.django_db
def test_send_notification_once_deduplicates_sent_event(monkeypatch):
    calls = []

    def fake_send(self, chat_id, text, **kwargs):
        calls.append((chat_id, text))

    monkeypatch.setattr("apps.telegram_bot.notifications.TelegramClient.send_message", fake_send)
    monkeypatch.setattr("apps.telegram_bot.notifications.TelegramClient.close", lambda self: None)

    assert send_notification_once(event_key="gmail:error:1", event_type="gmail_error", text="Error", config=_config()) is True
    assert send_notification_once(event_key="gmail:error:1", event_type="gmail_error", text="Error", config=_config()) is False

    delivery = TelegramDelivery.objects.get(event_key="gmail:error:1")
    assert delivery.status == TelegramDeliveryStatus.SENT
    assert delivery.attempts == 1
    assert delivery.error == ""
    assert len(calls) == 1


@pytest.mark.django_db
def test_send_notification_once_records_safe_error(monkeypatch):
    def fail_send(self, chat_id, text, **kwargs):
        raise RuntimeError("secret details")

    monkeypatch.setattr("apps.telegram_bot.notifications.TelegramClient.send_message", fail_send)
    monkeypatch.setattr("apps.telegram_bot.notifications.TelegramClient.close", lambda self: None)

    assert send_notification_once(event_key="backup:error:1", event_type="backup_error", text="Backup failed", config=_config()) is False

    delivery = TelegramDelivery.objects.get(event_key="backup:error:1")
    assert delivery.status == TelegramDeliveryStatus.FAILED
    assert delivery.attempts == 1
    assert delivery.error == "RuntimeError"
    assert "secret" not in delivery.error
