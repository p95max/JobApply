from __future__ import annotations

from django.db import connection
from datetime import timedelta
from django.core.management.base import BaseCommand
from apps.reports.models import CloudBackupSettings
from apps.reports.drive import get_drive_status, upload_backup_rotate_3
from apps.reports.services import export_csv
from apps.applications.models import JobApplication
from django.utils import timezone

import logging
import time

logger = logging.getLogger(__name__)

def _ts() -> str:
    return timezone.localtime().strftime("[%H:%M:%S %d-%m-%Y]")

INTERVAL_SECONDS = 30
BACKUP_EVERY = timedelta(minutes=5)


class Command(BaseCommand):
    help = "Runs a lightweight loop that performs Google Drive auto backups (latest + 2) every 5 minutes."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(
            f"{_ts()} Auto-backup worker started (tick={INTERVAL_SECONDS}s, backup={BACKUP_EVERY})."
        ))

        self._wait_until_table_exists("reports_cloudbackupsettings", timeout_seconds=120)

        while True:
            try:
                self._tick()
            except Exception as e:
                self.stderr.write(f"{_ts()} tick error: {e!r}")

            time.sleep(INTERVAL_SECONDS)

    def _wait_until_table_exists(self, table_name: str, timeout_seconds: int = 120) -> None:
        """
        Wait until migrations are applied (table exists). Avoids race with web container.
        """
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
            self.stdout.write(f"{_ts()} no users with auto-backup enabled")
            return

        for s in qs:
            user = s.user
            due = (s.last_run_at is None) or (now - s.last_run_at >= BACKUP_EVERY)

            if not due:
                remaining = BACKUP_EVERY - (now - s.last_run_at)
                self.stdout.write(f"{_ts()} user={user.id} skip (not due, remaining to next try={remaining})")
                continue

            drive_status = get_drive_status(user)
            if not (drive_status.get("connected") and drive_status.get("has_refresh_token")):
                self.stdout.write(f"{_ts()} user={user.id} disabled (drive not connected)")
                s.enabled = False
                s.save(update_fields=["enabled", "updated_at"])
                continue

            try:
                apps_qs = JobApplication.objects.filter(user=user).order_by("id")

                content = export_csv(apps_qs) # backup file type

                upload_backup_rotate_3(
                         user = user,
                         content_bytes = content,
                         ext = "csv",
                         mime_type = "text/csv",
                     )

                s.last_run_at = now
                s.save(update_fields=["last_run_at", "updated_at"])

                self.stdout.write(f"{_ts()} user={user.id} OK uploaded + rotated")
            except Exception as e:
                self.stderr.write(f"{_ts()} user={user.id} ERROR: {e!r}")

