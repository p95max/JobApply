from __future__ import annotations

import requests

from apps.telegram_bot.client import TelegramClient, telegram_error_detail


_REAL_SEND_MESSAGE = TelegramClient.send_message


class FakeResponse:
    def __init__(self, status_code=200, *, description="", text=""):
        self.status_code = status_code
        self._description = description
        self.text = text

    def json(self):
        return {"ok": self.status_code < 400, "description": self._description}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def post(self, url, *, json, timeout):
        self.calls.append((url, json, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def close(self):
        return None


def test_send_message_retries_html_parse_error_as_plain_text():
    client = TelegramClient("test")
    client.session = FakeSession(
        [
            FakeResponse(400, description="Bad Request: can't parse entities"),
            FakeResponse(200),
        ]
    )

    _REAL_SEND_MESSAGE(client, 123, "✅ <b>Connected</b> <broken>")

    assert len(client.session.calls) == 2
    first_payload = client.session.calls[0][1]
    fallback_payload = client.session.calls[1][1]
    assert first_payload["parse_mode"] == "HTML"
    assert "parse_mode" not in fallback_payload
    assert fallback_payload["text"] == "✅ Connected "
    assert client.session.outcomes == []


def test_send_message_retries_once_after_network_timeout(monkeypatch):
    monkeypatch.setattr("apps.telegram_bot.client.time.sleep", lambda seconds: None)
    client = TelegramClient("test")
    client.session = FakeSession([requests.Timeout("temporary"), FakeResponse(200)])

    _REAL_SEND_MESSAGE(client, 123, "🟢 <b>Online</b>")

    assert len(client.session.calls) == 2
    assert client.session.outcomes == []
    assert client.session.calls[0][1]["text"] == "🟢 <b>Online</b>"
    assert client.session.calls[1][1]["text"] == "🟢 <b>Online</b>"


def test_telegram_error_detail_includes_api_description():
    response = FakeResponse(400, description="Bad Request: can't parse entities")
    error = requests.HTTPError(response=response)

    assert telegram_error_detail(error) == "HTTP 400: Bad Request: can't parse entities"
