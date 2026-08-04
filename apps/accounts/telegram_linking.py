from __future__ import annotations

import hashlib
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserProfile


def bind_telegram_from_start(update: dict[str, Any]) -> UserProfile | None:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    text = str(message.get("text", "")).strip()

    if chat.get("type") != "private" or not text.startswith("/start "):
        return None

    token = text.split(maxsplit=1)[1].strip()
    if not token:
        return None

    try:
        chat_id = int(chat["id"])
        user_id = int(sender["id"])
    except (KeyError, TypeError, ValueError):
        return None

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = timezone.now()

    with transaction.atomic():
        profile = (
            UserProfile.objects.select_for_update()
            .filter(
                telegram_link_token_hash=token_hash,
                telegram_link_token_expires_at__gt=now,
            )
            .first()
        )
        if profile is None:
            return None

        profile.telegram_user_id = user_id
        profile.telegram_chat_id = chat_id
        profile.telegram_linked_at = now
        profile.telegram_link_token_hash = ""
        profile.telegram_link_token_expires_at = None
        profile.save(
            update_fields=[
                "telegram_user_id",
                "telegram_chat_id",
                "telegram_linked_at",
                "telegram_link_token_hash",
                "telegram_link_token_expires_at",
            ]
        )
        return profile


def linked_profile_for_ids(*, user_id: int, chat_id: int, owner_email: str = "") -> UserProfile | None:
    queryset = UserProfile.objects.select_related("user").filter(
        telegram_user_id=user_id,
        telegram_chat_id=chat_id,
    )
    if owner_email:
        queryset = queryset.filter(user__email__iexact=owner_email)
    return queryset.first()


def resolve_linked_chat_id(owner_email: str) -> int | None:
    if not owner_email:
        return None
    return (
        UserProfile.objects.filter(user__email__iexact=owner_email)
        .values_list("telegram_chat_id", flat=True)
        .first()
    )
