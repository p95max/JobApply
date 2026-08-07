from __future__ import annotations

import pytest
from django.test import override_settings

from apps.gmail_assistant.management.commands.run_gmail_assistant_worker import Command
from apps.gmail_assistant.models import GmailAssistantSettings


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_AUTO_SYNC_ENABLED=True)
def test_worker_syncs_only_users_who_enabled_ai(monkeypatch, django_user_model):
    enabled_user = django_user_model.objects.create_user("enabled", email="enabled@example.com")
    disabled_user = django_user_model.objects.create_user("disabled", email="disabled@example.com")
    GmailAssistantSettings.objects.create(user=enabled_user, ai_enabled=True)
    GmailAssistantSettings.objects.create(user=disabled_user, ai_enabled=False)
    credentials = object()
    calls = []

    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.get_google_credentials_for_user",
        lambda user: credentials,
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.GmailClient",
        lambda value: ("gmail", value),
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.sync_gmail_messages_for_user",
        lambda **kwargs: calls.append(kwargs) or {"proposals_created": 0},
    )

    Command()._tick()

    assert calls == [
        {
            "user": enabled_user,
            "gmail_client": ("gmail", credentials),
            "days": 180,
            "max_results_each": 500,
        }
    ]


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_AUTO_SYNC_ENABLED=False)
def test_worker_does_nothing_when_auto_sync_is_disabled(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user("enabled", email="enabled@example.com")
    GmailAssistantSettings.objects.create(user=user, ai_enabled=True)
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.sync_gmail_messages_for_user",
        lambda **kwargs: pytest.fail("worker must be disabled by environment"),
    )

    Command()._tick()


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_AUTO_SYNC_ENABLED=False)
def test_one_time_sync_can_run_when_auto_sync_is_disabled(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user("enabled", email="enabled@example.com")
    GmailAssistantSettings.objects.create(user=user, ai_enabled=True)
    calls = []

    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.get_google_credentials_for_user",
        lambda value: object(),
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.GmailClient",
        lambda value: value,
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.sync_gmail_messages_for_user",
        lambda **kwargs: calls.append(kwargs) or {"proposals_created": 0},
    )

    Command()._tick(force=True)

    assert [call["user"] for call in calls] == [user]


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_AUTO_SYNC_ENABLED=True)
def test_worker_notifies_the_linked_user_about_new_ai_results(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
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
        lambda **_kwargs: {"proposals_created": 3, "auto_applied": 1, "analyzed_by_ai": 4},
    )
    monkeypatch.setattr(
        "apps.gmail_assistant.management.commands.run_gmail_assistant_worker.send_notification_once",
        lambda **kwargs: notifications.append(kwargs) or True,
    )

    Command()._tick()

    assert len(notifications) == 1
    assert notifications[0]["recipient_email"] == "user@example.com"
    assert "AI analyzed: <b>4</b> emails" in notifications[0]["text"]
    assert "Manual review needed: <b>2</b> suggestions" in notifications[0]["text"]
    assert "Automatically accepted: <b>1</b> trusted updates" in notifications[0]["text"]
