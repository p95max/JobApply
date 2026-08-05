from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import TelegramCommandAudit


def is_rate_limited(*, user_id: int, chat_id: int, limit: int, window_seconds: int) -> bool:
    if limit <= 0:
        return False
    since = timezone.now() - timedelta(seconds=max(1, window_seconds))
    try:
        return (
            TelegramCommandAudit.objects.filter(
                user_id=user_id,
                chat_id=chat_id,
                created_at__gte=since,
            ).count()
            >= limit
        )
    except Exception:
        # Audit availability must not make read-only bot commands unavailable.
        return False


def record_command_audit(*, user_id: int, chat_id: int, command: str, result: str, duration_ms: int) -> None:
    """Persist only fixed command names and short outcomes, never input arguments."""
    TelegramCommandAudit.objects.create(
        user_id=user_id,
        chat_id=chat_id,
        command=command[:32],
        result=result[:32],
        duration_ms=max(0, duration_ms),
    )
