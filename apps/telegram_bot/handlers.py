from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import ObjectDoesNotExist

from .client import TelegramClient
from .config import TelegramConfig
from .permissions import is_update_allowed
from .selectors import get_application_summary, get_gmail_summary, get_status_snapshot
from .texts import applications_text, gmail_text, help_text, status_text

logger = logging.getLogger(__name__)


def _chat_id(update: dict[str, Any]) -> int:
    return int(update["message"]["chat"]["id"])


def handle_update(update: dict[str, Any], client: TelegramClient, config: TelegramConfig) -> None:
    if not is_update_allowed(update, config):
        logger.warning("Rejected unauthorized Telegram update")
        return

    message = update.get("message") or {}
    text = str(message.get("text", "")).strip().split(maxsplit=1)[0].split("@", 1)[0]
    chat_id = _chat_id(update)

    try:
        if text in {"/start", "/help"}:
            reply = help_text(config.environment_label)
        elif text == "/status":
            reply = status_text(config.environment_label, get_status_snapshot(config.owner_email))
        elif text == "/gmail":
            total, proposals = get_gmail_summary(config.owner_email)
            reply = gmail_text(total, proposals)
        elif text == "/applications":
            reply = applications_text(get_application_summary(config.owner_email))
        else:
            reply = "Unknown command. Use /help."
    except ObjectDoesNotExist:
        logger.exception("Telegram owner account was not found")
        reply = "JobApply owner account is not configured."
    except Exception:
        logger.exception("Telegram command failed")
        reply = "Command failed. Check JobApply logs."

    client.send_message(chat_id, reply)
