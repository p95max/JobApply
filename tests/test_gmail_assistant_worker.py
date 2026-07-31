from __future__ import annotations

import pytest
from django.test import override_settings

from apps.gmail_stats.management.commands.run_gmail_assistant_worker import Command
from apps.gmail_stats.models import GmailAssistantSettings


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
        "apps.gmail_stats.management.commands.run_gmail_assistant_worker.get_google_credentials_for_user",
        lambda user: credentials,
    )
    monkeypatch.setattr(
        "apps.gmail_stats.management.commands.run_gmail_assistant_worker.GmailClient",
        lambda value: ("gmail", value),
    )
    monkeypatch.setattr(
        "apps.gmail_stats.management.commands.run_gmail_assistant_worker.sync_gmail_messages_for_user",
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
        "apps.gmail_stats.management.commands.run_gmail_assistant_worker.sync_gmail_messages_for_user",
        lambda **kwargs: pytest.fail("worker must be disabled by environment"),
    )

    Command()._tick()
