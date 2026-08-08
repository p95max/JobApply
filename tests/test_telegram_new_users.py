from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.telegram_bot.config import TelegramConfig
from apps.telegram_bot.handlers import handle_update


class FakeClient:
    def __init__(self):
        self.messages = []

    def send_message(self, chat_id, text, *, reply_markup=None):
        self.messages.append((chat_id, text, reply_markup))


def config(**overrides) -> TelegramConfig:
    values = {
        "enabled": True,
        "token": "test-token",
        "default_chat_id": 100,
        "allowed_chat_ids": frozenset({100}),
        "allowed_user_ids": frozenset({200, 201}),
        "owner_user_id": 200,
        "owner_email": "owner@example.com",
        "environment_label": "TEST",
        "notifications_enabled": False,
        "rate_limit_count": 20,
        "rate_limit_window_seconds": 60,
    }
    values.update(overrides)
    return TelegramConfig(**values)


def update(user_id: int, command: str = "/newusers") -> dict:
    return {
        "message": {
            "text": command,
            "chat": {"id": 100, "type": "private"},
            "from": {"id": user_id},
        }
    }


@pytest.mark.django_db
def test_owner_can_list_active_users_registered_in_last_7_days(django_user_model):
    recent = django_user_model.objects.create_user("recent", email="recent@example.com")
    old = django_user_model.objects.create_user("old", email="old@example.com")
    inactive = django_user_model.objects.create_user("inactive", email="inactive@example.com", is_active=False)
    django_user_model.objects.filter(pk=old.pk).update(date_joined=timezone.now() - timedelta(days=8))
    django_user_model.objects.filter(pk=inactive.pk).update(date_joined=timezone.now() - timedelta(days=1))

    client = FakeClient()
    handle_update(update(200), client, config())

    text = client.messages[0][1]
    assert "New users · last 7 days" in text
    assert "recent@example.com" in text
    assert "old@example.com" not in text
    assert "inactive@example.com" not in text
    assert client.messages[0][2] is None


@pytest.mark.django_db
def test_newusers_is_owner_only():
    client = FakeClient()

    handle_update(update(201), client, config())

    assert "only to the bot owner" in client.messages[0][1]


@pytest.mark.django_db
def test_newusers_rejects_arguments():
    client = FakeClient()

    handle_update(update(200, "/newusers 30"), client, config())

    assert "does not accept command arguments" in client.messages[0][1]
