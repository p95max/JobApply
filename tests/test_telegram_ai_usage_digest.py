from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.gmail_assistant.usage_models import OpenAITokenUsage
from apps.gmail_stats.models import GmailMessage
from apps.telegram_bot.client import ADMIN_COMMANDS, CLIENT_COMMANDS
from apps.telegram_bot.config import TelegramConfig
from apps.telegram_bot.handlers import handle_update
from apps.telegram_bot.selectors import AIUsageDigest, AIUsageUserSummary, get_ai_usage_digest
from apps.telegram_bot.texts import ai_usage_digest_text


class FakeClient:
    def __init__(self):
        self.calls = []

    def send_message(self, chat_id, text, *, reply_markup=None):
        self.calls.append((chat_id, text, reply_markup))


def _owner_config() -> TelegramConfig:
    return TelegramConfig(
        enabled=True,
        token="test-token",
        default_chat_id=20,
        allowed_chat_ids=frozenset({20}),
        allowed_user_ids=frozenset({10}),
        owner_email="owner@example.test",
        environment_label="TEST",
        notifications_enabled=True,
        owner_user_id=10,
    )


def _digest() -> AIUsageDigest:
    now = timezone.now()
    return AIUsageDigest(
        since=now - timedelta(hours=24),
        until=now,
        requests=3,
        input_tokens=12_000,
        output_tokens=3_000,
        total_tokens=15_000,
        estimated_cost_usd=Decimal("0.00615"),
        active_user_count=2,
        top_users=(
            AIUsageUserSummary(
                email="heavy@example.test",
                requests=2,
                input_tokens=10_000,
                output_tokens=2_000,
                total_tokens=12_000,
                calls_left=38,
                daily_limit=50,
            ),
        ),
    )


@pytest.mark.django_db
def test_ai_usage_digest_uses_rolling_last_24_hours_across_users(django_user_model):
    now = timezone.now()
    user_a = django_user_model.objects.create_user("usage-a", email="a@example.test")
    user_b = django_user_model.objects.create_user("usage-b", email="b@example.test")
    message_a = GmailMessage.objects.create(
        user=user_a,
        message_id="usage-a-message",
        thread_id="usage-a-thread",
        received_at=now,
    )
    message_b = GmailMessage.objects.create(
        user=user_b,
        message_id="usage-b-message",
        thread_id="usage-b-thread",
        received_at=now,
    )

    usage_a = OpenAITokenUsage.objects.create(
        user=user_a,
        message=message_a,
        model_name="gpt-5.4-nano",
        input_tokens=10_000,
        output_tokens=2_000,
    )
    usage_b = OpenAITokenUsage.objects.create(
        user=user_b,
        message=message_b,
        model_name="gpt-5.4-nano",
        input_tokens=3_000,
        output_tokens=1_000,
    )
    old_usage = OpenAITokenUsage.objects.create(
        user=user_a,
        message=message_a,
        model_name="gpt-5.4-nano",
        input_tokens=999_999,
        output_tokens=999_999,
    )
    OpenAITokenUsage.objects.filter(pk=usage_a.pk).update(created_at=now - timedelta(hours=23))
    OpenAITokenUsage.objects.filter(pk=usage_b.pk).update(created_at=now - timedelta(hours=1))
    OpenAITokenUsage.objects.filter(pk=old_usage.pk).update(created_at=now - timedelta(hours=25))

    digest = get_ai_usage_digest(hours=24)

    assert digest.requests == 2
    assert digest.input_tokens == 13_000
    assert digest.output_tokens == 3_000
    assert digest.total_tokens == 16_000
    assert digest.active_user_count == 2
    assert [item.email for item in digest.top_users] == ["a@example.test", "b@example.test"]
    assert digest.top_users[0].total_tokens == 12_000
    assert digest.estimated_cost_usd == Decimal("0.00635")


def test_ai_usage_digest_text_matches_telegram_notification_style():
    text = ai_usage_digest_text(_digest(), scheduled=True)

    assert "📊 <b>Daily AI usage · rolling last 24h</b>" in text
    assert "🤖 Successful AI requests: <b>3</b>" in text
    assert "🪙 Tokens: <b>15,000</b>" in text
    assert "💰 Estimated API cost: <b>$0.0062</b>" in text
    assert "<code>heavy@example.test</code>" in text
    assert "quota 38/50 left" in text


@pytest.mark.django_db
def test_aiusage_command_is_owner_only_and_returns_realtime_digest(monkeypatch):
    monkeypatch.setattr("apps.telegram_bot.handlers.get_ai_usage_digest", lambda **kwargs: _digest())
    client = FakeClient()
    config = _owner_config()
    update = {
        "message": {
            "text": "/aiusage",
            "chat": {"id": 20, "type": "private"},
            "from": {"id": 10},
        }
    }

    handle_update(update, client, config)

    assert len(client.calls) == 1
    assert "📊 <b>AI usage · rolling last 24h</b>" in client.calls[0][1]
    assert client.calls[0][2]["inline_keyboard"][0][0]["text"] == "📊 Open AI statistics"


@pytest.mark.django_db
def test_aiusage_command_rejects_non_owner(monkeypatch):
    client = FakeClient()
    config = _owner_config()
    update = {
        "message": {
            "text": "/aiusage",
            "chat": {"id": 20, "type": "private"},
            "from": {"id": 99},
        }
    }
    monkeypatch.setattr("apps.telegram_bot.handlers.is_update_allowed", lambda update, config: True)
    monkeypatch.setattr("apps.telegram_bot.handlers.linked_profile_for_update", lambda update: None)

    handle_update(update, client, config)

    assert "Access denied" in client.calls[0][1]


def test_aiusage_is_published_only_in_admin_command_menu():
    assert not any(item["command"] == "aiusage" for item in CLIENT_COMMANDS)
    assert any(item["command"] == "aiusage" for item in ADMIN_COMMANDS)
