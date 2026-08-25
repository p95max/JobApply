from __future__ import annotations

from django.test import override_settings
from django.urls import resolve

from apps.telegram_bot.config import TelegramConfig
from apps.site_urls import jobapply_url
from apps.telegram_bot.handlers import CommandTimedOut, handle_update
from apps.telegram_bot.selectors import AIUsageSummary, ApplicationSummary


class FakeClient:
    def __init__(self):
        self.calls = []

    def send_message(self, chat_id, text, *, reply_markup=None):
        self.calls.append((chat_id, text, reply_markup))


def _config() -> TelegramConfig:
    return TelegramConfig(
        enabled=True,
        token="token",
        default_chat_id=10,
        allowed_chat_ids=frozenset({10}),
        allowed_user_ids=frozenset({20}),
        owner_email="owner@example.com",
        environment_label="TEST",
        notifications_enabled=True,
    )


def _update(command: str) -> dict:
    return {
        "update_id": 1,
        "message": {
            "text": command,
            "chat": {"id": 10, "type": "private"},
            "from": {"id": 20},
        },
    }


@override_settings(DJANGO_SITE_DOMAIN="jobapply.p95max.dev")
def test_jobapply_url_is_https_and_resolves():
    path = "/gmail_stats/gmail/assistant/"
    assert jobapply_url(path) == f"https://jobapply.p95max.dev{path}"
    assert resolve(path).url_name == "gmail_assistant"


def test_gmail_command_uses_gmail_assistant_button_when_pending(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr("apps.telegram_bot.handlers.get_gmail_summary", lambda email: (0, []))
    monkeypatch.setattr(
        "apps.telegram_bot.handlers.get_ai_usage_summary",
        lambda email: AIUsageSummary(calls_left=37, daily_limit=50, tokens_used_today=12450),
    )

    handle_update(_update("/gmail"), client, _config())

    _chat_id, text, markup = client.calls[0]
    assert "No pending proposals" in text
    assert "AI quota left: <b>37/50 calls</b>" in text
    assert "OpenAI tokens used today: <b>12,450</b>" in text
    assert markup is None

    monkeypatch.setattr("apps.telegram_bot.handlers.get_gmail_summary", lambda email: (2, []))
    handle_update(_update("/gmail"), client, _config())

    assert "Pending proposals: <b>2</b>" in client.calls[1][1]
    assert "AI quota left: <b>37/50 calls</b>" in client.calls[1][1]
    assert "OpenAI tokens used today: <b>12,450</b>" in client.calls[1][1]
    assert "href=" not in client.calls[1][1]
    assert client.calls[1][2] == {
        "inline_keyboard": [
            [
                {
                    "text": "📨 Open Gmail Assistant",
                    "url": "https://jobapply.p95max.dev/gmail_stats/gmail/assistant/",
                }
            ]
        ]
    }


def test_ping_confirms_that_bot_is_online():
    client = FakeClient()

    handle_update(_update("/ping"), client, _config())

    assert client.calls == [(10, "🟢 <b>JobApply bot is online</b>", None)]


def test_applications_command_uses_web_button(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(
        "apps.telegram_bot.handlers.get_application_summary",
        lambda email: ApplicationSummary(counts={"total": 0}, next_interview=None),
    )

    handle_update(_update("/applications"), client, _config())

    assert "href=" not in client.calls[0][1]
    assert client.calls[0][2] == {
        "inline_keyboard": [
            [
                {
                    "text": "📋 Open applications",
                    "url": "https://jobapply.p95max.dev/applications/",
                }
            ]
        ]
    }


def test_disconnect_deep_link_returns_confirmation():
    client = FakeClient()

    handle_update(_update("/start disconnected"), client, _config())

    assert client.calls == [
        (
            10,
            "🔌 <b>Telegram disconnected</b>\n\nThis chat is no longer connected to JobApply.",
            None,
        )
    ]


def test_timeout_returns_safe_message(monkeypatch):
    client = FakeClient()

    class TimeoutContext:
        def __enter__(self):
            raise CommandTimedOut

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr("apps.telegram_bot.handlers._command_timeout", lambda: TimeoutContext())

    handle_update(_update("/status"), client, _config())

    assert client.calls == [
        (10, "⏱ <b>Command timed out</b>\n\nPlease try again in a moment.", None)
    ]
