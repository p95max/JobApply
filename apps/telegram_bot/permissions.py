from __future__ import annotations

from typing import Any

from .config import TelegramConfig


def is_update_allowed(update: dict[str, Any], config: TelegramConfig) -> bool:
    message = update.get("message") or update.get("callback_query", {}).get("message") or {}
    chat = message.get("chat") or {}
    user = update.get("message", {}).get("from") or update.get("callback_query", {}).get("from") or {}

    if chat.get("type") != "private":
        return False

    try:
        chat_id = int(chat["id"])
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError):
        return False

    return chat_id in config.allowed_chat_ids and user_id in config.allowed_user_ids
