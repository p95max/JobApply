from __future__ import annotations

from django.test import override_settings
from django.urls import resolve

from apps.telegram_bot.config import TelegramConfig
from apps.telegram_bot.handlers import CommandTimedOut, _jobapply_url, handle_update


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
    assert _jobapply_url(path) == f"https://jobapply.p95max.dev{path}"
    assert resolve(path).url_name == "gmail_assistant"


def test_gmail_command_adds_open_button(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr("apps.telegram_bot.handlers.get_gmail_summary", lambda email: (0, []))

    handle_update(_update("/gmail"), client, _config())

    _chat_id, _text, markup = client.calls[0]
    button = markup["inline_keyboard"][0][0]
    assert button["text"] == "Open in JobApply"
    assert button["url"].endswith("/gmail_stats/gmail/assistant/")
    assert button["url"].startswith("https://")
    assert "callback_data" not in button


def test_disconnect_deep_link_returns_confirmation():
    client = FakeClient()

    handle_update(_update("/start disconnected"), client, _config())

    assert client.calls == [(10, "Telegram disconnected from JobApply.", None)]


def test_timeout_returns_safe_message(monkeypatch):
    client = FakeClient()

    class TimeoutContext:
        def __enter__(self):
            raise CommandTimedOut

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr("apps.telegram_bot.handlers._command_timeout", lambda: TimeoutContext())

    handle_update(_update("/status"), client, _config())

    assert client.calls == [(10, "Command timed out. Try again later.", None)]
