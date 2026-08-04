from __future__ import annotations

from apps.telegram_bot.client import BOT_COMMANDS, TelegramClient


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, bool]:
        return {"ok": True}


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post(self, url: str, *, json: dict, timeout: int):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse()

    def close(self) -> None:
        return None


def test_set_commands_publishes_native_telegram_menu():
    client = TelegramClient("test-token")
    session = FakeSession()
    client.session = session

    client.set_commands()

    assert session.calls == [
        {
            "url": "https://api.telegram.org/bottest-token/setMyCommands",
            "json": {"commands": list(BOT_COMMANDS)},
            "timeout": 10,
        }
    ]
    assert [item["command"] for item in BOT_COMMANDS] == [
        "help",
        "status",
        "gmail",
        "applications",
    ]
