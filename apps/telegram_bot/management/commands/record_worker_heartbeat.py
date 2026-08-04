from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.telegram_bot.heartbeat import BACKUP_WORKER, GMAIL_WORKER, TELEGRAM_BOT, record_heartbeat
from apps.telegram_bot.notifications import send_notification_once

ALLOWED_WORKERS = {BACKUP_WORKER, GMAIL_WORKER, TELEGRAM_BOT}


class Command(BaseCommand):
    help = "Record a safe heartbeat update for a known JobApply worker."

    def add_arguments(self, parser):
        parser.add_argument("worker_name", choices=sorted(ALLOWED_WORKERS))
        parser.add_argument("--interval", type=int, required=True)
        outcome = parser.add_mutually_exclusive_group(required=True)
        outcome.add_argument("--success", action="store_true")
        outcome.add_argument("--failure", action="store_true")
        parser.add_argument("--error-category", default="WorkerError")

    def handle(self, *args, **options):
        interval = int(options["interval"])
        if interval < 1:
            raise CommandError("--interval must be greater than zero")

        worker_name = str(options["worker_name"])
        success = bool(options["success"])
        error_category = str(options["error_category"] or "WorkerError")[:120]
        record_heartbeat(
            worker_name,
            expected_interval_seconds=interval,
            success=success,
            error=None if success else error_category,
        )

        if worker_name == BACKUP_WORKER and not success:
            day = timezone.localdate().isoformat()
            send_notification_once(
                event_key=f"backup_failed:{day}",
                event_type="backup_failed",
                text=(
                    "<b>JobApply backup failed</b>\n"
                    f"Error category: {error_category}\n"
                    "Check the backup service logs."
                ),
            )

        self.stdout.write(self.style.SUCCESS("Worker heartbeat recorded."))
