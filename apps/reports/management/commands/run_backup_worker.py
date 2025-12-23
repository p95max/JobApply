from __future__ import annotations
from django.db import connection
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from django.contrib.auth import get_user_model

from apps.reports.models import CloudBackupSettings
from apps.reports.drive import get_drive_status, upload_backup_rotate_3
from apps.reports.services import export_xlsx
from apps.applications.models import JobApplication

import logging
logger = logging.getLogger(__name__)



INTERVAL_SECONDS = 60
BACKUP_EVERY = timedelta(minutes=15)


class Command(BaseCommand):
    help = "Runs a lightweight loop that performs Google Drive auto backups (latest + 2) every 15 minutes."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Auto-backup worker started (tick=60s, backup=15m)."))

        self._wait_until_table_exists("reports_cloudbackupsettings", timeout_seconds=120)

        while True:
            try:
                self._tick()
            except Exception as e:
                self.stderr.write(f"[worker] tick error: {e!r}")

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
                    self.stdout.write(f"[worker] migrations ready: table '{table_name}' exists")
                    return
            except Exception:
                pass

            self.stdout.write("[worker] waiting for migrations...")
            time.sleep(2)

        raise RuntimeError(f"Timeout: table '{table_name}' did not appear in {timeout_seconds}s")

    def _tick(self):
        now = timezone.now()
        qs = CloudBackupSettings.objects.select_related("user").filter(enabled=True)

        if not qs.exists():
            self.stdout.write("[worker] no users with auto-backup enabled")
            return

        for s in qs:
            user = s.user
            due = (s.last_run_at is None) or (now - s.last_run_at >= BACKUP_EVERY)

            if not due:
                self.stdout.write(f"[worker] user={user.id} skip (not due)")
                continue

            drive_status = get_drive_status(user)
            if not (drive_status.get("connected") and drive_status.get("has_refresh_token")):
                self.stdout.write(f"[worker] user={user.id} disabled (drive not connected)")
                s.enabled = False
                s.save(update_fields=["enabled", "updated_at"])
                continue

            try:
                apps_qs = JobApplication.objects.filter(user=user).order_by("id")
                content = export_xlsx(apps_qs)

                upload_backup_rotate_3(user=user, content_bytes=content, ext="xlsx")

                s.last_run_at = now
                s.save(update_fields=["last_run_at", "updated_at"])

                self.stdout.write(f"[worker] user={user.id} OK uploaded + rotated")
            except Exception as e:
                self.stderr.write(f"[worker] user={user.id} ERROR: {e!r}")

