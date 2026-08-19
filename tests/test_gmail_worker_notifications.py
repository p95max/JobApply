from __future__ import annotations

import pytest
from django.utils import timezone

from apps.gmail_assistant.management.commands.run_gmail_assistant_worker import Command
from apps.gmail_assistant.models import GmailAssistantSettings
from apps.gmail_assistant.usage_models import OpenAITokenUsage
from apps.gmail_stats.models import GmailMessage
from apps.gmail_stats.services.sync_control import GmailSyncBusyError


@pytest.mark.django_db
def test_gmail_worker_notifies_when_oauth_is_missing(django_user_model, monkeypatch, settings):
    settings.GMAIL_ASSISTANT_AUTO_SYNC_ENABLED = True
    user = django_user_model.objects.create_user("owner", email="owner@example.com")
    GmailAssistantSettings.objects.create(user=user, ai_enabled=True)
    notifications = []

    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.get_google_credentials_for_user",
        lambda _user: None,
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.send_notification_once",
        lambda **kwargs: notifications.append(kwargs) or True,
    )

    Command()._tick()

    assert len(notifications) == 1
    assert notifications[0]["event_type"] == "gmail_oauth_required"
    assert "OAuth reconnect required" in notifications[0]["text"]
    assert GmailAssistantSettings.objects.get(user=user).last_error_message == "RuntimeError"


@pytest.mark.django_db
def test_gmail_worker_notifies_on_sync_error_without_raising(django_user_model, monkeypatch, settings):
    settings.GMAIL_ASSISTANT_AUTO_SYNC_ENABLED = True
    user = django_user_model.objects.create_user("owner", email="owner@example.com")
    GmailAssistantSettings.objects.create(user=user, ai_enabled=True)
    notifications = []

    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.get_google_credentials_for_user",
        lambda _user: object(),
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.GmailClient",
        lambda _credentials: object(),
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.sync_gmail_messages_for_user",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("secret details")),
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.send_notification_once",
        lambda **kwargs: notifications.append(kwargs) or False,
    )

    Command()._tick()

    assert len(notifications) == 1
    assert notifications[0]["event_type"] == "gmail_sync_error"
    assert "ValueError" in notifications[0]["text"]
    assert "secret details" not in notifications[0]["text"]
    assert GmailAssistantSettings.objects.get(user=user).last_error_message == "ValueError"


@pytest.mark.django_db
def test_gmail_worker_summary_links_to_gmail_assistant_and_reports_ai_quota(
    django_user_model, monkeypatch, settings
):
    settings.GMAIL_ASSISTANT_AUTO_SYNC_ENABLED = True
    settings.DJANGO_SITE_DOMAIN = "jobapply.p95max.dev"
    monkeypatch.setenv("GMAIL_ASSISTANT_AI_DAILY_LIMIT", "50")
    user = django_user_model.objects.create_user("owner", email="owner@example.com")
    GmailAssistantSettings.objects.create(
        user=user,
        ai_enabled=True,
        ai_daily_usage_date=timezone.localdate(),
        ai_daily_usage_count=47,
    )
    message = GmailMessage.objects.create(
        user=user,
        message_id="quota-summary-message",
        thread_id="quota-summary-thread",
        received_at=timezone.now(),
    )
    OpenAITokenUsage.objects.create(
        user=user,
        message=message,
        model_name="gpt-5.4-nano",
        input_tokens=1000,
        output_tokens=250,
    )
    notifications = []

    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.get_google_credentials_for_user",
        lambda _user: object(),
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.GmailClient",
        lambda _credentials: object(),
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.sync_gmail_messages_for_user",
        lambda **_kwargs: {
            "proposals_created": 2,
            "manual_review_required": 2,
            "auto_applied": 0,
            "analyzed_by_ai": 2,
        },
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.send_notification_once",
        lambda **kwargs: notifications.append(kwargs) or True,
    )

    Command()._tick()

    assert len(notifications) == 1
    assert notifications[0]["event_type"] == "gmail_assistant_summary"
    assert "AI quota left: <b>3/50 calls</b>" in notifications[0]["text"]
    assert "OpenAI tokens used today: <b>1,250</b>" in notifications[0]["text"]
    assert notifications[0]["reply_markup"] == {
        "inline_keyboard": [
            [
                {
                    "text": "📨 Open Gmail Assistant",
                    "url": "https://jobapply.p95max.dev/gmail_stats/gmail/assistant/",
                }
            ]
        ]
    }


@pytest.mark.django_db
def test_gmail_worker_sends_quota_summary_when_ai_was_used_without_new_proposals(
    django_user_model, monkeypatch, settings
):
    settings.GMAIL_ASSISTANT_AUTO_SYNC_ENABLED = True
    monkeypatch.setenv("GMAIL_ASSISTANT_AI_DAILY_LIMIT", "50")
    user = django_user_model.objects.create_user("ai-only", email="ai-only@example.com")
    GmailAssistantSettings.objects.create(
        user=user,
        ai_enabled=True,
        ai_daily_usage_date=timezone.localdate(),
        ai_daily_usage_count=1,
    )
    notifications = []

    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.get_google_credentials_for_user",
        lambda _user: object(),
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.GmailClient",
        lambda _credentials: object(),
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.sync_gmail_messages_for_user",
        lambda **_kwargs: {
            "proposals_created": 0,
            "manual_review_required": 0,
            "auto_applied": 0,
            "analyzed_by_ai": 1,
        },
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.send_notification_once",
        lambda **kwargs: notifications.append(kwargs) or True,
    )

    Command()._tick()

    assert len(notifications) == 1
    assert notifications[0]["event_type"] == "gmail_assistant_summary"
    assert "AI quota left: <b>49/50 calls</b>" in notifications[0]["text"]


@pytest.mark.django_db
def test_gmail_worker_treats_an_already_running_sync_as_expected(django_user_model, monkeypatch, settings):
    settings.GMAIL_ASSISTANT_AUTO_SYNC_ENABLED = True
    user = django_user_model.objects.create_user("owner", email="owner@example.com")
    GmailAssistantSettings.objects.create(user=user, ai_enabled=True, last_error_message="PreviousError")
    notifications = []

    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.get_google_credentials_for_user",
        lambda _user: object(),
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.GmailClient",
        lambda _credentials: object(),
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.sync_gmail_messages_for_user",
        lambda **_kwargs: (_ for _ in ()).throw(GmailSyncBusyError()),
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.send_notification_once",
        lambda **kwargs: notifications.append(kwargs) or True,
    )

    Command()._tick()

    assert notifications == []
    assert GmailAssistantSettings.objects.get(user=user).last_error_message == "PreviousError"
