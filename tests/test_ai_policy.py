from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.gmail_assistant.models import AnalysisClassifier, GmailAnalysis, GmailAssistantSettings
from apps.gmail_assistant.services.ai_policy import AIUsagePolicy, sanitize_email_text
from apps.gmail_stats.models import GmailMessage


@pytest.mark.parametrize(
    ("source", "secret"),
    [
        ("Ihr Passwort lautet: secret-value", "secret-value"),
        ("Benutzername: hb8Dkand582236", "hb8Dkand582236"),
        ("API_KEY=sk-test-secret", "sk-test-secret"),
        ("Open https://example.test/?token=private-token", "private-token"),
    ],
)
def test_sanitize_email_text_redacts_credentials(source, secret):
    sanitized = sanitize_email_text(source)

    assert secret not in sanitized
    assert "[REDACTED]" in sanitized


def test_policy_reads_bounded_environment(monkeypatch):
    monkeypatch.setenv("GMAIL_ASSISTANT_AI_DAILY_LIMIT", "50")
    monkeypatch.setenv("GMAIL_ASSISTANT_AI_CONFIDENCE_THRESHOLD", "80")
    monkeypatch.setenv("GMAIL_ASSISTANT_RULES_FALLBACK_ENABLED", "1")

    policy = AIUsagePolicy.from_environment()

    assert policy.daily_limit == 50
    assert policy.confidence_threshold == 80
    assert policy.rules_fallback_enabled is True
    assert policy.requires_manual_review(79) is True
    assert policy.requires_manual_review(80) is False


def test_policy_uses_safe_defaults_for_invalid_values(monkeypatch):
    monkeypatch.setenv("GMAIL_ASSISTANT_AI_DAILY_LIMIT", "invalid")
    monkeypatch.setenv("GMAIL_ASSISTANT_AI_CONFIDENCE_THRESHOLD", "999")
    monkeypatch.setenv("GMAIL_ASSISTANT_RULES_FALLBACK_ENABLED", "0")

    policy = AIUsagePolicy.from_environment()

    assert policy.daily_limit == 50
    assert policy.confidence_threshold == 100
    assert policy.rules_fallback_enabled is False


@pytest.mark.django_db
def test_daily_usage_excludes_ai_analyses_before_a_user_reset(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    message = GmailMessage.objects.create(
        user=user,
        message_id="message-1",
        thread_id="thread-1",
        received_at=timezone.now(),
    )
    GmailAnalysis.objects.create(
        user=user,
        message=message,
        classifier=AnalysisClassifier.AI,
        analyzed_at=timezone.now() - timedelta(minutes=1),
    )
    GmailAssistantSettings.objects.create(user=user, ai_daily_usage_reset_at=timezone.now())

    assert AIUsagePolicy.from_environment().daily_usage(user=user) == 0


@pytest.mark.django_db
def test_atomic_ai_reservations_stop_at_the_daily_limit(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    policy = AIUsagePolicy(daily_limit=2, confidence_threshold=80, rules_fallback_enabled=True)

    assert policy.reserve_call(user=user) is True
    assert policy.reserve_call(user=user) is True
    assert policy.reserve_call(user=user) is False

    settings_obj = GmailAssistantSettings.objects.get(user=user)
    assert settings_obj.ai_daily_usage_count == 2
    assert settings_obj.ai_daily_usage_date == timezone.localdate()
    assert policy.daily_usage(user=user) == 2
