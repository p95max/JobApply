from __future__ import annotations

import subprocess
from datetime import datetime

from django import template
from django.utils import timezone

register = template.Library()

_ALLOWED_TIMERS = {
    "jobapply-backup.timer",
    "jobapply-neon-sync.timer",
}


@register.simple_tag
def systemd_timer(unit_name: str) -> dict[str, str]:
    """Return the next run for one allow-listed systemd timer.

    Fails closed and returns an empty payload when systemd is unavailable, such
    as during local development or tests.
    """
    if unit_name not in _ALLOWED_TIMERS:
        return {}

    try:
        result = subprocess.run(
            [
                "systemctl",
                "show",
                unit_name,
                "--property=NextElapseUSecRealtime",
                "--value",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    raw = result.stdout.strip()
    if not raw or raw == "n/a":
        return {}

    try:
        # Example: Tue 2026-08-04 03:12:20 CEST
        date_part = " ".join(raw.split()[1:-1])
        next_run = datetime.strptime(date_part, "%Y-%m-%d %H:%M:%S")
        next_run = timezone.make_aware(next_run, timezone.get_current_timezone())
    except (ValueError, IndexError):
        return {}

    return {
        "iso": next_run.isoformat(),
        "display": timezone.localtime(next_run).strftime("%d.%m.%Y %H:%M"),
    }
