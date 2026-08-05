from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.telegram_linking import resolve_linked_chat_id

from .client import TelegramClient
from .config import TelegramConfig
from .models import TelegramDelivery, TelegramDeliveryStatus

logger = logging.getLogger(__name__)


def _target_chat_id(config: TelegramConfig) -> int | None:
    return resolve_linked_chat_id(config.owner_email) or config.default_chat_id


def send_notification(text: str, *, config: TelegramConfig | None = None) -> bool:
    config = config or TelegramConfig.from_env()
    chat_id = _target_chat_id(config)
    if not config.enabled or not config.notifications_enabled or chat_id is None:
        return False

    client = TelegramClient(config.token)
    try:
        client.send_message(chat_id, text)
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
    config: TelegramConfig | None = None,
) -> bool:
    config = config or TelegramConfig.from_env()
    chat_id = _target_chat_id(config)
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
        client.send_message(chat_id, text)
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
