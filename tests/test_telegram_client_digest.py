from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.utils import timezone

from apps.telegram_bot.client_digest import (
    ClientDigest,
    client_digest_keyboard,
    client_digest_text,
    send_daily_client_digests,
)
from apps.telegram_bot.config import TelegramConfig
from apps.telegram_bot.handlers import handle_update


class FakeClient:
    def __init__(self):
        self.messages = []
        self.answers = []
        self.edits = []

    def send_message(self, chat_id, text, *, reply_markup=None):
        self.messages.append((chat_id, text, reply_markup))

    def answer_callback_query(self, callback_id, text):
        self.answers.append((callback_id, text))

    def edit_message_text(self, chat_id, message_id, text):
        self.edits.append((chat_id, message_id, text))


def _config() -> TelegramConfig:
    return TelegramConfig(
        enabled=True,
        token="test-token",
        default_chat_id=999,
        allowed_chat_ids=frozenset({999}),
        allowed_user_ids=frozenset({888}),
        owner_email="owner@example.test",
        environment_label="TEST",
        notifications_enabled=True,
        owner_user_id=888,
    )


def _digest(*, hours: int = 24, activity: bool = True) -> ClientDigest:
    until = timezone.now()
    return ClientDigest(
        since=until - timedelta(hours=hours),
        until=until,
        gmail_events=5 if activity else 0,
        applications_created=2 if activity else 0,
        applications_updated=1 if activity else 0,
        pending_proposals=3,
        rejections=1 if activity else 0,
        interviews=1 if activity else 0,
        offers=0,
        action_required=1 if activity else 0,
        ai_requests=4 if activity else 0,
        ai_tokens=12345 if activity else 0,
        ai_calls_left=46,
        ai_daily_limit=50,
        backup_connected=True,
        backup_enabled=True,
        last_backup_at=until - timedelta(hours=2),
    )


def test_client_digest_text_and_keyboard_are_compact_and_actionable():
    text = client_digest_text(_digest(), scheduled=True)
    keyboard = client_digest_keyboard(hours=24)

    assert "Daily JobApply digest · last 24h" in text
    assert "Gmail events: <b>5</b>" in text
    assert "Applications created: <b>2</b>" in text
    assert "Rejections: <b>1</b>" in text
    assert "Interviews: <b>1</b>" in text
    assert "Tokens: <b>12,345</b>" in text
    assert "Last backup: ✅" in text
    assert keyboard["inline_keyboard"][0][0] == {
        "text": "📅 Digest for 7 days",
        "callback_data": "digest:168",
    }
    assert keyboard["inline_keyboard"][1][0]["url"].endswith("/gmail_stats/gmail/assistant/")


def test_client_digest_without_activity_uses_short_form():
    text = client_digest_text(_digest(activity=False), scheduled=True)

    assert "No new activity in this period" in text
    assert "Pending proposals: <b>3</b>" in text
    assert "Gmail events" not in text
    assert "Tokens:" not in text


@pytest.mark.django_db
def test_scheduled_digest_targets_each_linked_user_and_skips_unlinked_and_demo(
    django_user_model,
    monkeypatch,
):
    linked = django_user_model.objects.create_user("linked", email="linked@example.test")
    linked.userprofile.telegram_user_id = 101
    linked.userprofile.telegram_chat_id = 201
    linked.userprofile.telegram_linked_at = timezone.now()
    linked.userprofile.save(update_fields=["telegram_user_id", "telegram_chat_id", "telegram_linked_at"])

    django_user_model.objects.create_user("unlinked", email="unlinked@example.test")

    demo = django_user_model.objects.create_user("demo", email="demo@example.test")
    demo.userprofile.is_demo_user = True
    demo.userprofile.telegram_user_id = 102
    demo.userprofile.telegram_chat_id = 202
    demo.userprofile.save(update_fields=["is_demo_user", "telegram_user_id", "telegram_chat_id"])

    calls = []
    monkeypatch.setattr(
        "apps.telegram_bot.client_digest.build_client_digest",
        lambda **kwargs: _digest(),
    )
    monkeypatch.setattr(
        "apps.telegram_bot.client_digest.send_notification_once",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    sent = send_daily_client_digests()

    assert sent == 1
    assert len(calls) == 1
    assert calls[0]["recipient_email"] == "linked@example.test"
    assert calls[0]["event_type"] == "client_daily_digest"
    assert calls[0]["event_key"].startswith(f"client_daily_digest:{linked.pk}:")
    assert calls[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "digest:168"


@pytest.mark.django_db
def test_weekly_digest_callback_uses_linked_account_and_edits_same_message(
    django_user_model,
    monkeypatch,
):
    user = django_user_model.objects.create_user("client", email="client@example.test")
    profile = user.userprofile
    profile.telegram_user_id = 321
    profile.telegram_chat_id = 654
    profile.telegram_linked_at = timezone.now()
    profile.save(update_fields=["telegram_user_id", "telegram_chat_id", "telegram_linked_at"])

    observed = {}

    def fake_build_client_digest(*, user, hours, until=None):
        observed["user_id"] = user.pk
        observed["hours"] = hours
        return _digest(hours=hours)

    monkeypatch.setattr("apps.telegram_bot.handlers.build_client_digest", fake_build_client_digest)
    client = FakeClient()
    update = {
        "callback_query": {
            "id": "digest-callback",
            "data": "digest:168",
            "from": {"id": 321},
            "message": {"message_id": 77, "chat": {"id": 654, "type": "private"}},
        }
    }

    handle_update(update, client, _config())

    assert observed == {"user_id": user.pk, "hours": 168}
    assert client.edits[0][0:2] == (654, 77)
    assert "JobApply digest · last 7 days" in client.edits[0][2]
    assert client.answers[-1] == ("digest-callback", "Digest updated.")


def test_client_digest_timer_runs_at_09_berlin_and_is_persistent():
    timer = Path(settings.BASE_DIR, "deploy/vps/systemd/jobapply-client-digest.timer").read_text()

    assert "OnCalendar=*-*-* 09:00:00 Europe/Berlin" in timer
    assert "Persistent=true" in timer
