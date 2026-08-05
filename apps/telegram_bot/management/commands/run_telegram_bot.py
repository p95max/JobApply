from __future__ import annotations

import logging
import signal
import time

import requests
from django.core.management.base import BaseCommand, CommandError

from apps.telegram_bot.client import TelegramClient
from apps.telegram_bot.config import TelegramConfig
from apps.telegram_bot.handlers import handle_update
from apps.telegram_bot.heartbeat import TELEGRAM_BOT, record_heartbeat

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the JobApply Telegram Bot using long polling."

    def handle(self, *args, **options):
        try:
            config = TelegramConfig.from_env()
            config.validate_for_polling()
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if not config.enabled:
            self.stdout.write("Telegram Bot is disabled.")
            return

        stop_requested = False

        def request_stop(signum, frame):
            nonlocal stop_requested
            stop_requested = True

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)

        client = TelegramClient(config.token)
        offset: int | None = None

        try:
            client.set_commands()
            self.stdout.write(self.style.SUCCESS("Telegram command menu published."))
        except (requests.RequestException, RuntimeError, ValueError) as error:
            logger.warning("Telegram command menu publication failed: %s", type(error).__name__)

        self.stdout.write(self.style.SUCCESS("Telegram Bot polling started."))

        try:
            while not stop_requested:
                try:
                    record_heartbeat(TELEGRAM_BOT, expected_interval_seconds=60)
                    updates = client.get_updates(offset)
                    for update in updates:
                        offset = int(update["update_id"]) + 1
                        handle_update(update, client, config)
                    record_heartbeat(TELEGRAM_BOT, expected_interval_seconds=60, success=True)
                except (requests.RequestException, RuntimeError, ValueError) as error:
                    record_heartbeat(TELEGRAM_BOT, expected_interval_seconds=60, success=False, error=error)
                    logger.warning("Telegram polling iteration failed: %s", type(error).__name__)
                    time.sleep(5)
        finally:
            client.close()
            self.stdout.write("Telegram Bot polling stopped.")
