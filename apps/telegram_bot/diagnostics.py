from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from .heartbeat import BACKUP_WORKER, GMAIL_WORKER, TELEGRAM_BOT, HeartbeatStatus, get_heartbeat_status


KNOWN_UNITS = (
    "jobapply-web.service",
    "jobapply-gmail-worker.service",
    "jobapply-backup.service",
    "jobapply-telegram-bot.service",
)


@dataclass(frozen=True)
class HealthSnapshot:
    database_ok: bool
    free_disk_mb: int
    worker_heartbeats: tuple[HeartbeatStatus, ...]


@dataclass(frozen=True)
class DoctorSnapshot:
    health: HealthSnapshot
    branch: str
    is_dirty: bool
    pending_migrations: int
    worker_errors: tuple[str, ...]
    unit_states: tuple[tuple[str, str], ...]


def get_health_snapshot() -> HealthSnapshot:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            database_ok = cursor.fetchone() == (1,)
    except Exception:
        database_ok = False
    free_disk_mb = shutil.disk_usage(settings.BASE_DIR).free // (1024 * 1024)
    return HealthSnapshot(
        database_ok=database_ok,
        free_disk_mb=free_disk_mb,
        worker_heartbeats=tuple(get_heartbeat_status(name) for name in (GMAIL_WORKER, BACKUP_WORKER, TELEGRAM_BOT)),
    )


def get_doctor_snapshot() -> DoctorSnapshot:
    health = get_health_snapshot()
    branch = _git_output("branch", "--show-current") or "unknown"
    is_dirty = bool(_git_output("status", "--porcelain"))
    try:
        executor = MigrationExecutor(connection)
        pending_migrations = len(executor.migration_plan(executor.loader.graph.leaf_nodes()))
    except Exception:
        pending_migrations = -1
    worker_errors = tuple(
        f"{item.worker_name}: {item.last_error_message}"
        for item in health.worker_heartbeats
        if item.last_error_message
    )
    return DoctorSnapshot(
        health=health,
        branch=branch,
        is_dirty=is_dirty,
        pending_migrations=pending_migrations,
        worker_errors=worker_errors,
        unit_states=tuple((unit, _unit_state(unit)) for unit in KNOWN_UNITS),
    )


def _git_output(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=Path(settings.BASE_DIR),
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _unit_state(unit: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except OSError:
        return "unavailable"
    state = result.stdout.strip().lower()
    return state if state in {"active", "inactive", "failed", "unknown"} else "unknown"
