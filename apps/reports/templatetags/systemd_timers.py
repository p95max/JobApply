from __future__ import annotations

import subprocess
from datetime import datetime, time, timedelta

from django import template
from django.utils import timezone

from apps.telegram_bot.models import WorkerHeartbeat

register = template.Library()

_ALLOWED_TIMERS = {
    "jobapply-backup.timer",
    "jobapply-neon-sync.timer",
}

_HEARTBEAT_WORKERS = {
    "jobapply-backup.timer": "backup_worker",
    "jobapply-neon-sync.timer": "neon_sync_worker",
}

_FALLBACK_SCHEDULES = {
    "jobapply-backup.timer": {
        "weekday": None,
        "start": time(3, 0),
        "end": time(3, 15),
    },
    "jobapply-neon-sync.timer": {
        "weekday": 6,
        "start": time(3, 30),
        "end": time(3, 50),
    },
}


def _parse_systemd_datetime(raw: str) -> datetime | None:
    raw = raw.strip()
    if not raw or raw == "n/a":
        return None

    try:
        date_part = " ".join(raw.split()[1:-1])
        parsed = datetime.strptime(date_part, "%Y-%m-%d %H:%M:%S")
    except (ValueError, IndexError):
        return None
    return timezone.make_aware(parsed, timezone.get_current_timezone())


def _systemctl_show(unit_name: str, properties: tuple[str, ...]) -> dict[str, str]:
    command = ["systemctl", "show", unit_name]
    for property_name in properties:
        command.append(f"--property={property_name}")

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value.strip()
    return values


def _fallback_next_run(unit_name: str) -> dict[str, str]:
    schedule = _FALLBACK_SCHEDULES[unit_name]
    local_now = timezone.localtime()
    target_date = local_now.date()
    weekday = schedule["weekday"]

    if weekday is None:
        start_today = timezone.make_aware(
            datetime.combine(target_date, schedule["start"]),
            timezone.get_current_timezone(),
        )
        if local_now >= start_today:
            target_date += timedelta(days=1)
    else:
        days_ahead = (weekday - target_date.weekday()) % 7
        target_date += timedelta(days=days_ahead)
        start_target = timezone.make_aware(
            datetime.combine(target_date, schedule["start"]),
            timezone.get_current_timezone(),
        )
        if local_now >= start_target:
            target_date += timedelta(days=7)

    start_at = timezone.make_aware(
        datetime.combine(target_date, schedule["start"]),
        timezone.get_current_timezone(),
    )
    display = (
        f"{target_date.strftime('%d.%m.%Y')} "
        f"{schedule['start'].strftime('%H:%M')}–{schedule['end'].strftime('%H:%M')}"
    )
    return {
        "iso": start_at.isoformat(),
        "display": display,
        "estimated": "1",
    }


def _last_success_from_heartbeat(unit_name: str) -> datetime | None:
    worker_name = _HEARTBEAT_WORKERS.get(unit_name)
    if not worker_name:
        return None

    heartbeat = WorkerHeartbeat.objects.filter(worker_name=worker_name).first()
    if not heartbeat:
        return None

    return heartbeat.last_success_at or heartbeat.last_seen_at


@register.simple_tag
def systemd_timer(unit_name: str) -> dict[str, object]:
    """Return last successful heartbeat and next execution metadata."""
    if unit_name not in _ALLOWED_TIMERS:
        return {}

    timer_values = _systemctl_show(
        unit_name,
        ("LastTriggerUSec", "NextElapseUSecRealtime"),
    )

    last_run = _last_success_from_heartbeat(unit_name)
    if last_run is None:
        last_run = _parse_systemd_datetime(timer_values.get("LastTriggerUSec", ""))

    next_run = _parse_systemd_datetime(timer_values.get("NextElapseUSecRealtime", ""))
    payload: dict[str, object] = {"last_successful": bool(last_run)}

    if last_run:
        payload.update(
            {
                "last_iso": last_run.isoformat(),
                "last_display": timezone.localtime(last_run).strftime("%d.%m.%Y %H:%M"),
            }
        )
    if next_run:
        payload.update(
            {
                "iso": next_run.isoformat(),
                "display": timezone.localtime(next_run).strftime("%d.%m.%Y %H:%M"),
            }
        )
    else:
        payload.update(_fallback_next_run(unit_name))
    return payload
