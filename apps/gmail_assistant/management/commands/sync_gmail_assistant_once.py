from __future__ import annotations

from apps.gmail_assistant.management.commands.run_gmail_assistant_worker import Command as WorkerCommand


class Command(WorkerCommand):
    help = "Synchronize Gmail Assistant messages once for every opted-in user."

    def handle(self, *args, **options):
        self._tick(force=True)
