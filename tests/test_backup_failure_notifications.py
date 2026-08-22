from __future__ import annotations

from django.core.management import call_command

from apps.accounts.models import UserProfile
from apps.reports.management.commands.run_backup_worker import (
    Command as BackupWorkerCommand,
    _safe_error_detail,
)
from apps.reports.models import CloudBackupSettings
from apps.telegram_bot.config import TelegramConfig
from apps.telegram_bot.heartbeat import BACKUP_WORKER
from apps.telegram_bot.models import TelegramDelivery, WorkerHeartbeat
from apps.telegram_bot.notifications import send_notification_once


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
    text = str(calls[0]["text"])
    assert "Google Drive backup stopped" in text
    assert "Reconnect Google Drive" in text
    assert "missing_refresh_token" in text
    assert "Google refresh token is missing" in text
    assert calls[0]["reply_markup"] == {
        "inline_keyboard": [
            [
                {
                    "text": "🔗 Reconnect Google Drive",
                    "url": "https://jobapply.p95max.dev/reports/drive/",
                }
            ]
        ]
    }


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
    text = str(calls[0]["text"])
    assert "Google Drive backup stopped" in text
    assert "Error: <code>refresh</code>" in text
    assert "Google session expired" in text
    assert calls[0]["reply_markup"]["inline_keyboard"][0][0]["text"] == "🔗 Reconnect Google Drive"


def test_drive_failure_notification_routes_to_affected_users_linked_chat(db, django_user_model):
    owner = django_user_model.objects.create_user("owner-route", email="owner-route@example.com")
    affected = django_user_model.objects.create_user("affected-route", email="affected@example.com")
    UserProfile.objects.create(user=owner, telegram_user_id=1001, telegram_chat_id=2001)
    UserProfile.objects.create(user=affected, telegram_user_id=1002, telegram_chat_id=2002)
    config = TelegramConfig(
        enabled=True,
        token="test-token",
        default_chat_id=9999,
        allowed_chat_ids=frozenset({9999}),
        allowed_user_ids=frozenset({9998}),
        owner_email="owner-route@example.com",
        environment_label="TEST",
        notifications_enabled=True,
    )

    sent = send_notification_once(
        event_key="drive-user-routing",
        event_type="drive_backup_failed",
        recipient_email="affected@example.com",
        text="Drive failed",
        config=config,
    )

    assert sent is True
    delivery = TelegramDelivery.objects.get(event_key="drive-user-routing")
    assert delivery.chat_id == 2002
    assert delivery.chat_id != 2001
    assert delivery.chat_id != 9999


def test_drive_failure_notification_does_not_fall_back_to_owner_for_unlinked_user(db, django_user_model):
    owner = django_user_model.objects.create_user("owner-no-fallback", email="owner-no-fallback@example.com")
    django_user_model.objects.create_user("unlinked", email="unlinked@example.com")
    UserProfile.objects.create(user=owner, telegram_user_id=3001, telegram_chat_id=4001)
    config = TelegramConfig(
        enabled=True,
        token="test-token",
        default_chat_id=4999,
        allowed_chat_ids=frozenset({4999}),
        allowed_user_ids=frozenset({4998}),
        owner_email="owner-no-fallback@example.com",
        environment_label="TEST",
        notifications_enabled=True,
    )

    sent = send_notification_once(
        event_key="drive-no-owner-fallback",
        event_type="drive_backup_failed",
        recipient_email="unlinked@example.com",
        text="Drive failed",
        config=config,
    )

    assert sent is False
    assert not TelegramDelivery.objects.filter(event_key="drive-no-owner-fallback").exists()


def test_drive_error_detail_redacts_credentials_and_escapes_html():
    detail = (
        "HttpError 403 <forbidden> access_token=secret-token "
        "Authorization: Bearer abc.def refresh_token=refresh-secret"
    )

    safe = _safe_error_detail(detail)

    assert "secret-token" not in safe
    assert "abc.def" not in safe
    assert "refresh-secret" not in safe
    assert "[REDACTED]" in safe
    assert "&lt;forbidden&gt;" in safe
