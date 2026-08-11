from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.telegram_bot.heartbeat import BACKUP_WORKER, NEON_SYNC_WORKER, get_heartbeat_status
from apps.telegram_bot.models import WorkerHeartbeat


@pytest.mark.django_db
def test_record_backup_worker_success():
    call_command(
        "record_worker_heartbeat",
        BACKUP_WORKER,
        interval=86400,
        success=True,
    )

    heartbeat = WorkerHeartbeat.objects.get(worker_name=BACKUP_WORKER)
    status = get_heartbeat_status(BACKUP_WORKER)

    assert heartbeat.expected_interval_seconds == 86400
    assert heartbeat.last_success_at is not None
    assert heartbeat.last_error_message == ""
    assert status.is_stale is False


@pytest.mark.django_db
def test_record_backup_worker_failure_uses_safe_category():
    call_command(
        "record_worker_heartbeat",
        BACKUP_WORKER,
        interval=86400,
        failure=True,
        error_category="BackupFailed",
    )

    heartbeat = WorkerHeartbeat.objects.get(worker_name=BACKUP_WORKER)

    assert heartbeat.last_error_at is not None
    assert heartbeat.last_error_message == "BackupFailed"


@pytest.mark.django_db
def test_record_neon_sync_success():
    call_command(
        "record_worker_heartbeat",
        NEON_SYNC_WORKER,
        interval=604800,
        success=True,
    )

    heartbeat = WorkerHeartbeat.objects.get(worker_name=NEON_SYNC_WORKER)

    assert heartbeat.expected_interval_seconds == 604800
    assert heartbeat.last_success_at is not None
