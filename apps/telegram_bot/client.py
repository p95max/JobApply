from __future__ import annotations

import html
import logging
import re
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

CLIENT_COMMANDS: tuple[dict[str, str], ...] = (
    {"command": "help", "description": "Show user commands"},
    {"command": "ping", "description": "Check whether the bot is online"},
    {"command": "gmail", "description": "Show pending email events"},
    {"command": "applications", "description": "Show application statistics"},
    {"command": "digest", "description": "Show your JobApply digest for the last 24 hours"},
)

ADMIN_COMMANDS: tuple[dict[str, str], ...] = CLIENT_COMMANDS + (
    {"command": "admin", "description": "Show administrator commands"},
    {"command": "status", "description": "Show JobApply service status"},
    {"command": "aiusage", "description": "Show AI usage for the last 24 hours"},
    {"command": "newusers", "description": "Show users registered in the last 7 days"},
    {"command": "health", "description": "Run runtime health checks"},
    {"command": "doctor", "description": "Run owner diagnostics"},
    {"command": "deploy", "description": "Queue production deploy"},
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def telegram_error_detail(error: BaseException) -> str:
    if not isinstance(error, requests.HTTPError) or error.response is None:
        return type(error).__name__
    response = error.response
    description = ""
    try:
        payload = response.json()
        description = str(payload.get("description") or "").strip()
    except (ValueError, TypeError, AttributeError):
        description = str(getattr(response, "text", "") or "").strip()[:300]
    detail = f"HTTP {response.status_code}"
    return f"{detail}: {description}" if description else detail


def _plain_text_from_html(value: str) -> str:
    return html.unescape(_HTML_TAG_RE.sub("", value))


def _is_html_parse_error(error: requests.HTTPError) -> bool:
    if error.response is None or error.response.status_code != 400:
        return False
    try:
        description = str(error.response.json().get("description") or "").casefold()
    except (ValueError, TypeError, AttributeError):
        description = str(error.response.text or "").casefold()
    return "parse entities" in description or "unsupported start tag" in description


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

    def set_commands(self, *, admin_chat_id: int | None = None) -> None:
        self._set_commands(
            commands=CLIENT_COMMANDS,
            scope={"type": "all_private_chats"},
        )
        if admin_chat_id is not None:
            self._set_commands(
                commands=ADMIN_COMMANDS,
                scope={"type": "chat", "chat_id": admin_chat_id},
            )

    def _set_commands(self, *, commands: tuple[dict[str, str], ...], scope: dict[str, Any]) -> None:
        response = self.session.post(
            f"{self.base_url}/setMyCommands",
            json={"commands": list(commands), "scope": scope},
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

        try:
            self._send_message_payload(payload)
            return
        except requests.HTTPError as error:
            if not _is_html_parse_error(error):
                raise
            logger.warning(
                "Telegram HTML formatting rejected; retrying as plain text: %s",
                telegram_error_detail(error),
            )

        fallback_payload = dict(payload)
        fallback_payload["text"] = _plain_text_from_html(text)
        fallback_payload.pop("parse_mode", None)
        self._send_message_payload(fallback_payload)

    def _send_message_payload(self, payload: dict[str, Any]) -> None:
        last_error: requests.RequestException | None = None
        for attempt in range(2):
            try:
                response = self.session.post(
                    f"{self.base_url}/sendMessage",
                    json=payload,
                    timeout=10,
                )
                response.raise_for_status()
                return
            except (requests.Timeout, requests.ConnectionError) as error:
                last_error = error
                if attempt == 0:
                    time.sleep(0.2)
                    continue
                raise
            except requests.HTTPError as error:
                response = error.response
                if response is not None and response.status_code >= 500 and attempt == 0:
                    last_error = error
                    time.sleep(0.2)
                    continue
                raise
        if last_error is not None:
            raise last_error

    def answer_callback_query(self, callback_query_id: str, text: str) -> None:
        response = self.session.post(
            f"{self.base_url}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text[:200]},
            timeout=10,
        )
        response.raise_for_status()

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        response = self.session.post(
            f"{self.base_url}/editMessageText",
            json=payload,
            timeout=10,
        )
        response.raise_for_status()

    def close(self) -> None:
        self.session.close()
