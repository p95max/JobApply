from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

from .models import WorkerHeartbeat

GMAIL_WORKER = "gmail_worker"
TELEGRAM_BOT = "telegram_bot"
BACKUP_WORKER = "backup_worker"
NEON_SYNC_WORKER = "neon_sync_worker"


@dataclass(frozen=True)
class HeartbeatStatus:
    worker_name: str
    last_seen_at: datetime | None
    is_stale: bool
    last_error_message: str
    last_success_at: datetime | None = None


def record_heartbeat(
    worker_name: str,
    *,
    expected_interval_seconds: int,
    success: bool | None = None,
    error: Exception | str | None = None,
) -> WorkerHeartbeat:
    now = timezone.now()
    defaults: dict[str, object] = {
        "expected_interval_seconds": max(1, int(expected_interval_seconds)),
        "last_seen_at": now,
    }
    if success is True:
        defaults.update(last_success_at=now, last_error_message="")
    elif success is False:
        defaults.update(
            last_error_at=now,
            last_error_message=(type(error).__name__ if isinstance(error, Exception) else str(error or "Error"))[:120],
        )
    heartbeat, _created = WorkerHeartbeat.objects.update_or_create(worker_name=worker_name, defaults=defaults)
    return heartbeat


def get_heartbeat_status(worker_name: str, *, grace_multiplier: int = 2) -> HeartbeatStatus:
    heartbeat = WorkerHeartbeat.objects.filter(worker_name=worker_name).first()
    if heartbeat is None:
        return HeartbeatStatus(worker_name, None, True, "")
    stale_after = heartbeat.last_seen_at + timedelta(
        seconds=heartbeat.expected_interval_seconds * max(1, grace_multiplier)
    )
    return HeartbeatStatus(
        worker_name=worker_name,
        last_seen_at=heartbeat.last_seen_at,
        is_stale=timezone.now() > stale_after,
        last_error_message=heartbeat.last_error_message,
        last_success_at=heartbeat.last_success_at,
    )
