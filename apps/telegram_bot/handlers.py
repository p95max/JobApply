from __future__ import annotations

import logging
import signal
import subprocess
from contextlib import contextmanager
from typing import Any, Iterator

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from apps.accounts.telegram_linking import bind_telegram_from_start

from .client import TelegramClient
from .config import TelegramConfig
from .permissions import is_update_allowed
from .selectors import get_application_summary, get_gmail_summary, get_status_snapshot
from .texts import applications_text, gmail_text, help_text, status_text

logger = logging.getLogger(__name__)
COMMAND_TIMEOUT_SECONDS = 8
DEPLOY_SERVICE = "jobapply-deploy.service"


class CommandTimedOut(Exception):
    pass


@contextmanager
def _command_timeout(seconds: int = COMMAND_TIMEOUT_SECONDS) -> Iterator[None]:
    def _raise_timeout(signum, frame):
        raise CommandTimedOut

    previous_handler = signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _chat_id(update: dict[str, Any]) -> int:
    return int(update["message"]["chat"]["id"])


def _user_id(update: dict[str, Any]) -> int:
    return int(update["message"]["from"]["id"])


def _jobapply_url(path: str = "/") -> str:
    domain = str(getattr(settings, "DJANGO_SITE_DOMAIN", "jobapply.p95max.dev")).strip().strip("/")
    if domain.startswith(("http://", "https://")):
        base_url = domain
    else:
        base_url = f"https://{domain}"
    return f"{base_url}{path}"


def _queue_deploy(update: dict[str, Any], config: TelegramConfig) -> str:
    if config.owner_user_id is None or _user_id(update) != config.owner_user_id:
        logger.warning("Rejected owner-only /deploy command from Telegram user %s", _user_id(update))
        return "This command is available only to the bot owner."

    active = subprocess.run(
        ["systemctl", "is-active", "--quiet", DEPLOY_SERVICE],
        check=False,
        timeout=3,
    ).returncode == 0
    if active:
        return "Deploy is already running or waiting in the background queue."

    result = subprocess.run(
        ["sudo", "-n", "systemctl", "--no-block", "start", DEPLOY_SERVICE],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        logger.error("Could not queue deploy: %s", result.stderr.strip())
        return "Could not queue deploy. Check the Telegram bot service logs."

    return (
        "🚀 Deploy queued.\n"
        "It will wait until the shared background queue is free, then run tests and deploy master."
    )


def handle_update(update: dict[str, Any], client: TelegramClient, config: TelegramConfig) -> None:
    message = update.get("message") or {}
    text_raw = str(message.get("text", "")).strip()

    if text_raw == "/start disconnected":
        client.send_message(_chat_id(update), "Telegram disconnected from JobApply.")
        return

    if text_raw.startswith("/start "):
        try:
            profile = bind_telegram_from_start(update)
        except Exception:
            logger.exception("Telegram account binding failed")
            profile = None
        if profile is not None:
            client.send_message(_chat_id(update), "Telegram connected to JobApply.")
            return

    if not is_update_allowed(update, config):
        logger.warning("Rejected unauthorized Telegram update")
        return

    text = text_raw.split(maxsplit=1)[0].split("@", 1)[0]
    chat_id = _chat_id(update)
    reply_markup = None

    try:
        with _command_timeout():
            if text in {"/start", "/help"}:
                reply = help_text(config.environment_label)
            elif text == "/status":
                reply = status_text(config.environment_label, get_status_snapshot(config.owner_email))
            elif text == "/gmail":
                total, proposals = get_gmail_summary(config.owner_email)
                reply = gmail_text(total, proposals)
                reply_markup = {
                    "inline_keyboard": [[{"text": "Open in JobApply", "url": _jobapply_url("/gmail_stats/gmail/assistant/")}]]
                }
            elif text == "/applications":
                reply = applications_text(get_application_summary(config.owner_email))
            elif text == "/deploy":
                reply = _queue_deploy(update, config)
            else:
                reply = "Unknown command. Use /help."
    except CommandTimedOut:
        logger.warning("Telegram command timed out: %s", text)
        reply = "Command timed out. Try again later."
        reply_markup = None
    except ObjectDoesNotExist:
        logger.exception("Telegram owner account was not found")
        reply = "JobApply owner account is not configured."
        reply_markup = None
    except Exception:
        logger.exception("Telegram command failed")
        reply = "Command failed. Check JobApply logs."
        reply_markup = None

    client.send_message(chat_id, reply, reply_markup=reply_markup)
