from __future__ import annotations

import pytest

from apps.gmail_assistant.management.commands.run_gmail_assistant_worker import Command
from apps.gmail_assistant.models import GmailAssistantSettings
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
