from __future__ import annotations

from datetime import timedelta
from html import escape
import logging
import re
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from apps.applications.models import JobApplication
from apps.reports.drive import DriveError, get_drive_status, upload_backup_rotate_3
from apps.reports.models import CloudBackupSettings
from apps.reports.services import export_csv
from apps.telegram_bot.notifications import send_notification_once

logger = logging.getLogger(__name__)


def _ts() -> str:
    return timezone.localtime().strftime("[%H:%M:%S %d-%m-%Y]")


INTERVAL_SECONDS = 300
BACKUP_EVERY = timedelta(seconds=settings.PERSONAL_DRIVE_BACKUP_INTERVAL_SECONDS)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?P<prefix>\b(?:access[_ -]?token|refresh[_ -]?token|id[_ -]?token|client[_ -]?secret|api[_ -]?key|authorization|password)\b\s*[:=]\s*)(?P<value>[^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_QUERY_SECRET_RE = re.compile(
    r"(?i)(?P<prefix>[?&](?:access_token|refresh_token|token|key|client_secret)=)(?P<value>[^&#\s]+)"
)


def _safe_error_detail(detail: object, *, max_length: int = 240) -> str:
    """Return a short Telegram-safe diagnostic without credentials or multiline noise."""
    text = " ".join(str(detail or "Unknown error").split())
    # Redact complete Authorization/Bearer credentials before the generic
    # key/value pass; otherwise `Authorization: Bearer abc...` would replace
    # only the word `Bearer` and leave the credential behind.
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _SECRET_VALUE_RE.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    text = _QUERY_SECRET_RE.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    if len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "…"
    return escape(text)


def _notify_backup_failure(user, *, code: str, detail: str) -> None:
    """Notify the affected linked Telegram chat at most once per error/day."""
    today = timezone.localdate().isoformat()
    auth_failure = code in {"auth", "refresh", "disconnected", "missing_refresh_token"}
    safe_code = escape(str(code or "unknown"))
    safe_detail = _safe_error_detail(detail)

    if auth_failure:
        text = (
            "🚨 <b>Google Drive backup stopped</b>\n\n"
            "JobApply can no longer access your Google Drive. "
            "Reconnect Google Drive in JobApply to resume automatic backups."
            f"\n\n🔎 Error: <code>{safe_code}</code>"
            f"\n📝 Details: <code>{safe_detail}</code>"
        )
    else:
        text = (
            "⚠️ <b>Google Drive backup failed</b>\n\n"
            "The scheduled JobApply backup could not be uploaded. "
            "Automatic backup will retry on the next cycle."
            f"\n\n🔎 Error: <code>{safe_code}</code>"
            f"\n📝 Details: <code>{safe_detail}</code>"
        )

    send_notification_once(
        event_key=f"drive_backup_failed:{user.pk}:{code}:{today}",
        event_type="drive_backup_failed",
        recipient_email=getattr(user, "email", None),
        text=text,
    )
    logger.warning(
        "Personal Drive backup failure user=%s code=%s detail=%s",
        user.pk,
        code,
        detail,
    )


class Command(BaseCommand):
    help = "Runs a lightweight loop that performs scheduled personal Google Drive backups (latest + 2)."

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS(
                f"{_ts()} Auto-backup worker started (tick={INTERVAL_SECONDS}s, backup={BACKUP_EVERY})."
            )
        )

        self._wait_until_table_exists("reports_cloudbackupsettings", timeout_seconds=120)

        while True:
            try:
                self._tick()
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"{_ts()} tick error: {e!r}"))

            time.sleep(INTERVAL_SECONDS)

    def _wait_until_table_exists(self, table_name: str, timeout_seconds: int = 120) -> None:
        """Wait until migrations are applied (table exists). Avoids race with web container."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM information_schema.tables WHERE table_name = %s LIMIT 1;",
                        [table_name],
                    )
                    ok = cursor.fetchone() is not None
                if ok:
                    self.stdout.write(f"{_ts()} migrations ready: table '{table_name}' exists")
                    return
            except Exception:
                pass

            self.stdout.write(f"{_ts()} waiting for migrations...")
            time.sleep(2)

        raise RuntimeError(f"{_ts()} Timeout: table '{table_name}' did not appear in {timeout_seconds}s")

    def _tick(self):
        now = timezone.now()
        qs = CloudBackupSettings.objects.select_related("user").filter(enabled=True)

        if not qs.exists():
            self.stdout.write(self.style.WARNING(f"{_ts()} no users with auto-backup enabled"))
            return

        for s in qs:
            user = s.user
            due = (s.last_run_at is None) or (now - s.last_run_at >= BACKUP_EVERY)

            if not due:
                remaining_seconds = max(
                    int((BACKUP_EVERY - (now - s.last_run_at)).total_seconds()),
                    0,
                )
                remaining = timedelta(seconds=remaining_seconds)
                self.stdout.write(
                    f"{_ts()} user={user.id} skip (not due, remaining to next check={remaining})"
                )
                continue

            drive_status = get_drive_status(user)
            if not drive_status.get("connected"):
                self.stdout.write(
                    self.style.WARNING(f"{_ts()} user={user.id} skip (drive not connected)")
                )
                _notify_backup_failure(
                    user,
                    code="disconnected",
                    detail=str(drive_status.get("error") or "Drive is not connected"),
                )
                continue
            if not drive_status.get("has_refresh_token"):
                self.stdout.write(
                    self.style.WARNING(f"{_ts()} user={user.id} skip (refresh token missing)")
                )
                _notify_backup_failure(
                    user,
                    code="missing_refresh_token",
                    detail="Google refresh token is missing",
                )
                continue

            try:
                apps_qs = JobApplication.objects.filter(user=user).order_by("id")
                content = export_csv(apps_qs)

                upload_backup_rotate_3(
                    user=user,
                    content_bytes=content,
                    ext="csv",
                    mime_type="text/csv",
                )

                s.last_run_at = now
                s.save(update_fields=["last_run_at", "updated_at"])

                self.stdout.write(
                    self.style.SUCCESS(f"{_ts()} user={user.id} Autobackup uploaded + rotated")
                )

            except DriveError as error:
                code = getattr(error, "code", "drive_error") or "drive_error"
                self.stderr.write(
                    self.style.ERROR(f"{_ts()} user={user.id} DriveError[{code}]: {error}")
                )
                _notify_backup_failure(user, code=code, detail=str(error))
            except Exception as error:
                self.stderr.write(self.style.ERROR(f"{_ts()} user={user.id} ERROR: {error!r}"))
                _notify_backup_failure(
                    user,
                    code="unexpected",
                    detail=f"{type(error).__name__}: {error}",
                )
