from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.gmail_assistant.models import GmailAssistantSettings
from apps.gmail_assistant.services.sync import sync_gmail_messages_for_user
from apps.gmail_stats.services.credentials import get_google_credentials_for_user
from apps.gmail_stats.services.gmail_client import GmailClient
from apps.telegram_bot.heartbeat import GMAIL_WORKER, record_heartbeat
from apps.telegram_bot.notifications import send_notification_once


class Command(BaseCommand):
    help = "Periodically sync Gmail Assistant messages for users who enabled AI analysis."

    def handle(self, *args, **options):
        interval = settings.GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS
        self.stdout.write(self.style.SUCCESS(f"Gmail Assistant worker started (interval={interval}s)."))
        while True:
            try:
                self._tick()
                record_heartbeat(GMAIL_WORKER, expected_interval_seconds=interval, success=True)
            except Exception as error:
                record_heartbeat(GMAIL_WORKER, expected_interval_seconds=interval, success=False, error=error)
                self.stderr.write(self.style.ERROR(f"Gmail Assistant worker error: {error}"))
                time.sleep(2)
                continue
            time.sleep(interval)

    def _notify_error(self, assistant_settings: GmailAssistantSettings, error: Exception, *, oauth: bool) -> None:
        date_key = timezone.localdate().isoformat()
        event_type = "gmail_oauth_required" if oauth else "gmail_sync_error"
        title = "Gmail OAuth reconnect required" if oauth else "Gmail sync failed"
        send_notification_once(
            event_key=f"{event_type}:{assistant_settings.user_id}:{date_key}",
            event_type=event_type,
            text=(
                f"<b>{title}</b>\n"
                f"User ID: <code>{assistant_settings.user_id}</code>\n"
                f"Error: <code>{type(error).__name__}</code>"
            ),
        )

    def _tick(self, *, force: bool = False):
        if not force and not settings.GMAIL_ASSISTANT_AUTO_SYNC_ENABLED:
            return

        enabled_settings = GmailAssistantSettings.objects.select_related("user").filter(ai_enabled=True)
        for assistant_settings in enabled_settings:
            try:
                credentials = get_google_credentials_for_user(assistant_settings.user)
                if not credentials:
                    error = RuntimeError("Google Gmail is not connected")
                    self._notify_error(assistant_settings, error, oauth=True)
                    raise error
                result = sync_gmail_messages_for_user(
                    user=assistant_settings.user,
                    gmail_client=GmailClient(credentials),
                    days=180,
                    max_results_each=500,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"user={assistant_settings.user_id} Gmail Assistant sync complete: {result}"
                    )
                )
            except Exception as error:
                assistant_settings.last_error_at = timezone.now()
                assistant_settings.last_error_message = type(error).__name__
                assistant_settings.save(update_fields=["last_error_at", "last_error_message", "updated_at"])
                if str(error) != "Google Gmail is not connected":
                    self._notify_error(assistant_settings, error, oauth=False)
                self.stderr.write(
                    self.style.ERROR(f"user={assistant_settings.user_id} Gmail Assistant error: {error}")
                )
