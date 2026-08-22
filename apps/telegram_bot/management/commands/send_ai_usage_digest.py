from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.telegram_bot.config import TelegramConfig
from apps.telegram_bot.handlers import _jobapply_url
from apps.telegram_bot.notifications import send_notification_once, url_keyboard
from apps.telegram_bot.selectors import get_ai_usage_digest
from apps.telegram_bot.texts import ai_usage_digest_text


class Command(BaseCommand):
    help = "Send the owner-only Telegram AI usage digest for the rolling last 24 hours."

    def handle(self, *args, **options):
        config = TelegramConfig.from_env()
        if not config.enabled or not config.notifications_enabled:
            self.stdout.write("Telegram notifications are disabled; AI usage digest skipped.")
            return
        if not config.token or not config.owner_email:
            self.stdout.write(self.style.WARNING("Telegram owner notification settings are incomplete; digest skipped."))
            return

        digest = get_ai_usage_digest(hours=24)
        report_url = _jobapply_url("/reports/ai-statistics/")
        sent = send_notification_once(
            event_key=f"ai_usage_daily_digest:{timezone.localdate().isoformat()}",
            event_type="ai_usage_daily_digest",
            recipient_email=config.owner_email,
            text=ai_usage_digest_text(digest, scheduled=True),
            config=config,
            reply_markup=url_keyboard("📊 Open AI statistics", report_url),
        )
        if sent:
            self.stdout.write(self.style.SUCCESS("AI usage digest sent."))
        else:
            self.stdout.write("AI usage digest was already sent or could not be delivered.")
