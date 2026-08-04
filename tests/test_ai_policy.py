from __future__ import annotations

import pytest

from apps.gmail_assistant.services.ai_policy import AIUsagePolicy, sanitize_email_text


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
