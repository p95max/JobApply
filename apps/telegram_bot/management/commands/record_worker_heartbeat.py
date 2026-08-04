from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.telegram_bot.heartbeat import BACKUP_WORKER, GMAIL_WORKER, TELEGRAM_BOT, record_heartbeat

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

        success = bool(options["success"])
        record_heartbeat(
            options["worker_name"],
            expected_interval_seconds=interval,
            success=success,
            error=None if success else str(options["error_category"]),
        )
        self.stdout.write(self.style.SUCCESS("Worker heartbeat recorded."))
