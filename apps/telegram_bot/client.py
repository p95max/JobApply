from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

CLIENT_COMMANDS: tuple[dict[str, str], ...] = (
    {"command": "help", "description": "Show user commands"},
    {"command": "gmail", "description": "Show pending email events"},
    {"command": "applications", "description": "Show application statistics"},
    {"command": "admin", "description": "Show administrator commands"},
)

BOT_COMMANDS = CLIENT_COMMANDS


class TelegramClient:
    def __init__(self, token: str, *, timeout: int = 35) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.timeout = timeout
        self.session = requests.Session()

    def get_updates(self, offset: int | None = None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        response = self.session.get(
            f"{self.base_url}/getUpdates",
            params=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError("Telegram getUpdates returned an error")
        return data.get("result", [])

    def set_commands(self) -> None:
        response = self.session.post(
            f"{self.base_url}/setMyCommands",
            json={"commands": list(BOT_COMMANDS)},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError("Telegram setMyCommands returned an error")

    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        response = self.session.post(
            f"{self.base_url}/sendMessage",
            json=payload,
            timeout=10,
        )
        response.raise_for_status()

    def answer_callback_query(self, callback_query_id: str, text: str) -> None:
        response = self.session.post(
            f"{self.base_url}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text[:200]},
            timeout=10,
        )
        response.raise_for_status()

    def edit_message_text(self, chat_id: int, message_id: int, text: str) -> None:
        response = self.session.post(
            f"{self.base_url}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        response.raise_for_status()

    def close(self) -> None:
        self.session.close()
