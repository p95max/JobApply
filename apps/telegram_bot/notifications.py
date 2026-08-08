from __future__ import annotations

import logging
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.telegram_linking import resolve_linked_chat_id

from .client import TelegramClient
from .config import TelegramConfig
from .models import TelegramDelivery, TelegramDeliveryStatus

logger = logging.getLogger(__name__)


def _target_chat_id(config: TelegramConfig, *, recipient_email: str | None = None) -> int | None:
    if recipient_email:
        linked_chat_id = resolve_linked_chat_id(recipient_email)
        if linked_chat_id is not None:
            return linked_chat_id
        if recipient_email.casefold() != config.owner_email.casefold():
            return None
    return resolve_linked_chat_id(config.owner_email) or config.default_chat_id


def url_keyboard(text: str, url: str) -> dict[str, list[list[dict[str, str]]]]:
    return {"inline_keyboard": [[{"text": text, "url": url}]]}


def send_notification(
    text: str,
    *,
    recipient_email: str | None = None,
    config: TelegramConfig | None = None,
    reply_markup: dict[str, Any] | None = None,
) -> bool:
    config = config or TelegramConfig.from_env()
    chat_id = _target_chat_id(config, recipient_email=recipient_email)
    if not config.enabled or not config.notifications_enabled or chat_id is None:
        return False

    client = TelegramClient(config.token)
    try:
        client.send_message(chat_id, text, reply_markup=reply_markup)
        return True
    except Exception as error:
        logger.warning("Telegram notification delivery failed: %s", type(error).__name__)
        return False
    finally:
        client.close()


def send_notification_once(
    *,
    event_key: str,
    event_type: str,
    text: str,
    recipient_email: str | None = None,
    config: TelegramConfig | None = None,
    reply_markup: dict[str, Any] | None = None,
) -> bool:
    config = config or TelegramConfig.from_env()
    chat_id = _target_chat_id(config, recipient_email=recipient_email)
    if not config.enabled or not config.notifications_enabled or chat_id is None:
        return False

    try:
        with transaction.atomic():
            delivery, created = TelegramDelivery.objects.get_or_create(
                event_key=event_key[:180],
                defaults={
                    "event_type": event_type[:64],
                    "chat_id": chat_id,
                },
            )
    except IntegrityError:
        delivery = TelegramDelivery.objects.get(event_key=event_key[:180])
        created = False

    if not created and delivery.status == TelegramDeliveryStatus.SENT:
        return False
    if delivery.attempts >= 3:
        return False

    delivery.attempts += 1
    delivery.status = TelegramDeliveryStatus.PENDING
    delivery.error = ""
    delivery.chat_id = chat_id
    delivery.save(update_fields=["attempts", "status", "error", "chat_id"])

    client = TelegramClient(config.token)
    try:
        client.send_message(chat_id, text, reply_markup=reply_markup)
    except Exception as error:
        delivery.status = TelegramDeliveryStatus.FAILED
        delivery.error = type(error).__name__[:120]
        delivery.save(update_fields=["status", "error"])
        logger.warning(
            "Telegram notification delivery failed: %s",
            type(error).__name__,
            extra={"event_type": event_type},
        )
        return False
    finally:
        client.close()

    delivery.status = TelegramDeliveryStatus.SENT
    delivery.sent_at = timezone.now()
    delivery.error = ""
    delivery.save(update_fields=["status", "sent_at", "error"])
    return True
