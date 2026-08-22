from __future__ import annotations

from apps.telegram_bot.client import ADMIN_COMMANDS, CLIENT_COMMANDS, TelegramClient


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


def test_set_commands_publishes_client_and_admin_scopes():
    client = TelegramClient("test-token")
    session = FakeSession()
    client.session = session

    client.set_commands(admin_chat_id=100)

    assert session.calls == [
        {
            "url": "https://api.telegram.org/bottest-token/setMyCommands",
            "json": {
                "commands": list(CLIENT_COMMANDS),
                "scope": {"type": "all_private_chats"},
            },
            "timeout": 10,
        },
        {
            "url": "https://api.telegram.org/bottest-token/setMyCommands",
            "json": {
                "commands": list(ADMIN_COMMANDS),
                "scope": {"type": "chat", "chat_id": 100},
            },
            "timeout": 10,
        },
    ]
    assert [item["command"] for item in CLIENT_COMMANDS] == ["help", "ping", "gmail", "applications"]
    assert [item["command"] for item in ADMIN_COMMANDS] == [
        "help",
        "ping",
        "gmail",
        "applications",
        "admin",
        "status",
        "newusers",
        "aiusage",
        "health",
        "doctor",
        "deploy",
    ]
