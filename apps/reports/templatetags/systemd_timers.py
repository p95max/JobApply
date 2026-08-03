from __future__ import annotations

import subprocess
from datetime import datetime, time, timedelta

from django import template
from django.utils import timezone

register = template.Library()

_ALLOWED_TIMERS = {
    "jobapply-backup.timer",
    "jobapply-neon-sync.timer",
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


@register.simple_tag
def systemd_timer(unit_name: str) -> dict[str, object]:
    """Return last and next execution metadata for one allow-listed timer."""
    if unit_name not in _ALLOWED_TIMERS:
        return {}

    timer_values = _systemctl_show(
        unit_name,
        ("LastTriggerUSec", "NextElapseUSecRealtime"),
    )
    service_values = _systemctl_show(
        unit_name.removesuffix(".timer") + ".service",
        ("Result", "ExecMainStatus"),
    )

    last_run = _parse_systemd_datetime(timer_values.get("LastTriggerUSec", ""))
    next_run = _parse_systemd_datetime(timer_values.get("NextElapseUSecRealtime", ""))
    last_successful = bool(
        last_run
        and service_values.get("Result") == "success"
        and service_values.get("ExecMainStatus", "0") == "0"
    )

    payload: dict[str, object] = {"last_successful": last_successful}
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
