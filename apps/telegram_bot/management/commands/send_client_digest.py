from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.telegram_bot.client_digest import send_daily_client_digests


class Command(BaseCommand):
    help = "Send the rolling 24-hour JobApply digest to Telegram-linked users."

    def handle(self, *args, **options):
        sent = send_daily_client_digests()
        self.stdout.write(self.style.SUCCESS(f"Client digests sent: {sent}"))
