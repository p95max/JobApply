from __future__ import annotations

from django.core.management import call_command

from apps.reports.management.commands.run_backup_worker import Command as BackupWorkerCommand
from apps.reports.models import CloudBackupSettings
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


def test_personal_drive_worker_alerts_when_refresh_token_is_missing(
    db,
    django_user_model,
    monkeypatch,
):
    user = django_user_model.objects.create_user(
        username="backup-user",
        email="backup@example.com",
    )
    settings_obj = CloudBackupSettings.objects.create(
        user=user,
        drive_connected=True,
        enabled=True,
    )
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "apps.reports.management.commands.run_backup_worker.get_drive_status",
        lambda user: {"connected": True, "has_refresh_token": False},
    )
    monkeypatch.setattr(
        "apps.reports.management.commands.run_backup_worker.send_notification_once",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    BackupWorkerCommand()._tick()

    settings_obj.refresh_from_db()
    assert settings_obj.enabled is True
    assert len(calls) == 1
    assert calls[0]["event_type"] == "drive_backup_failed"
    assert calls[0]["recipient_email"] == "backup@example.com"
    assert "Google Drive backup stopped" in str(calls[0]["text"])
    assert "Reconnect Google Drive" in str(calls[0]["text"])


def test_personal_drive_worker_alerts_on_drive_auth_error(
    db,
    django_user_model,
    monkeypatch,
):
    from apps.reports.drive import DriveError

    user = django_user_model.objects.create_user(
        username="backup-auth-user",
        email="backup-auth@example.com",
    )
    CloudBackupSettings.objects.create(
        user=user,
        drive_connected=True,
        enabled=True,
    )
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "apps.reports.management.commands.run_backup_worker.get_drive_status",
        lambda user: {"connected": True, "has_refresh_token": True},
    )
    monkeypatch.setattr(
        "apps.reports.management.commands.run_backup_worker.export_csv",
        lambda queryset: b"csv",
    )
    monkeypatch.setattr(
        "apps.reports.management.commands.run_backup_worker.upload_backup_rotate_3",
        lambda **kwargs: (_ for _ in ()).throw(
            DriveError("Google session expired. Reconnect Google Drive.", code="refresh")
        ),
    )
    monkeypatch.setattr(
        "apps.reports.management.commands.run_backup_worker.send_notification_once",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    BackupWorkerCommand()._tick()

    assert len(calls) == 1
    assert calls[0]["event_type"] == "drive_backup_failed"
    assert "drive_backup_failed:" in str(calls[0]["event_key"])
    assert "Google Drive backup stopped" in str(calls[0]["text"])
