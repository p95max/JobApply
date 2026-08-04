from __future__ import annotations

from django.core.management import call_command

from apps.telegram_bot.heartbeat import BACKUP_WORKER
from apps.telegram_bot.models import WorkerHeartbeat


def test_backup_failure_records_heartbeat_and_sends_safe_notification(db, monkeypatch):
    calls: list[dict[str, str]] = []

    monkeypatch.setattr(
        "apps.telegram_bot.management.commands.record_worker_heartbeat.send_notification_once",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    call_command(
        "record_worker_heartbeat",
        BACKUP_WORKER,
        interval=86400,
        failure=True,
        error_category="BackupFailed",
    )

    heartbeat = WorkerHeartbeat.objects.get(worker_name=BACKUP_WORKER)
    assert heartbeat.last_error_message == "BackupFailed"
    assert len(calls) == 1
    assert calls[0]["event_type"] == "backup_failed"
    assert calls[0]["event_key"].startswith("backup_failed:")
    assert "BackupFailed" in calls[0]["text"]
    assert "DATABASE_URL" not in calls[0]["text"]


def test_successful_backup_does_not_send_failure_notification(db, monkeypatch):
    calls: list[dict[str, str]] = []

    monkeypatch.setattr(
        "apps.telegram_bot.management.commands.record_worker_heartbeat.send_notification_once",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    call_command(
        "record_worker_heartbeat",
        BACKUP_WORKER,
        interval=86400,
        success=True,
    )

    heartbeat = WorkerHeartbeat.objects.get(worker_name=BACKUP_WORKER)
    assert heartbeat.last_error_message == ""
    assert calls == []
