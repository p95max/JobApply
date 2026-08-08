from __future__ import annotations

import logging
import signal
import time
from contextlib import contextmanager
from typing import Any, Iterator

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from apps.accounts.telegram_linking import bind_telegram_from_start

from .audit import is_rate_limited, record_command_audit
from .client import TelegramClient
from .config import TelegramConfig
from .deployments import apply_deploy_callback, parse_deploy_callback, prepare_deploy_request
from .diagnostics import get_doctor_snapshot, get_health_snapshot
from .notifications import url_keyboard
from .permissions import is_update_allowed, linked_profile_for_update
from .proposal_actions import apply_callback_action, parse_callback_data
from .selectors import get_application_summary, get_gmail_summary, get_owner, get_status_snapshot
from .texts import (
    admin_text,
    applications_text,
    deploy_keyboard,
    doctor_text,
    gmail_text,
    health_text,
    help_text,
    status_text,
)

logger = logging.getLogger(__name__)
COMMAND_TIMEOUT_SECONDS = 8
UNLINKED_REPLY_LIMIT = 1
UNLINKED_REPLY_WINDOW_SECONDS = 300


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


def _callback_user_id(update: dict[str, Any]) -> int:
    return int(update["callback_query"]["from"]["id"])


def _callback_chat_id(update: dict[str, Any]) -> int:
    return int(update["callback_query"]["message"]["chat"]["id"])


def _jobapply_url(path: str = "/") -> str:
    domain = str(getattr(settings, "DJANGO_SITE_DOMAIN", "jobapply.p95max.dev")).strip().strip("/")
    if domain.startswith(("http://", "https://")):
        base_url = domain
    else:
        base_url = f"https://{domain}"
    return f"{base_url}{path}"


def _is_owner(user_id: int, chat_id: int, config: TelegramConfig) -> bool:
    return (
        config.owner_user_id is not None
        and user_id == config.owner_user_id
        and config.default_chat_id is not None
        and chat_id == config.default_chat_id
    )


def _handle_callback(update: dict[str, Any], client: TelegramClient, config: TelegramConfig) -> None:
    callback = update.get("callback_query") or {}
    callback_id = str(callback.get("id") or "")
    proposal_callback = parse_callback_data(callback.get("data"))
    deploy_callback = parse_deploy_callback(callback.get("data"))
    if proposal_callback is None and deploy_callback is None:
        _answer_callback(client, callback_id, "This action is not available.")
        return

    user_id = _callback_user_id(update)
    chat_id = _callback_chat_id(update)
    started = time.monotonic()

    if deploy_callback is not None:
        if not _is_owner(user_id, chat_id, config):
            _record_audit(user_id, chat_id, "deploy_callback", "forbidden", started)
            _answer_callback(client, callback_id, "This action is available only to the bot owner.")
            return
        if is_rate_limited(
            user_id=user_id,
            chat_id=chat_id,
            limit=config.rate_limit_count,
            window_seconds=config.rate_limit_window_seconds,
        ):
            _record_audit(user_id, chat_id, "deploy_callback", "rate_limited", started)
            _answer_callback(client, callback_id, "Too many requests. Please wait a moment.")
            return
        request_id, action = deploy_callback
        if not config.deploy_enabled:
            _finish_callback(
                client=client,
                callback=callback,
                callback_id=callback_id,
                chat_id=chat_id,
                user_id=user_id,
                command="deploy_callback",
                outcome="disabled",
                message="Deploy is disabled by configuration.",
                started=started,
            )
            return
        result = apply_deploy_callback(
            request_id=request_id,
            action=action,
            telegram_user_id=user_id,
            chat_id=chat_id,
        )
        _finish_callback(
            client=client,
            callback=callback,
            callback_id=callback_id,
            chat_id=chat_id,
            user_id=user_id,
            command="deploy_callback",
            outcome=result.outcome,
            message=result.message,
            started=started,
        )
        return

    assert proposal_callback is not None
    if not is_update_allowed(update, config):
        _record_audit(user_id, chat_id, "proposal_callback", "forbidden", started)
        _answer_callback(client, callback_id, "Connect this Telegram chat to JobApply first.")
        return
    profile = linked_profile_for_update(update)
    if profile is None and not _is_owner(user_id, chat_id, config):
        _record_audit(user_id, chat_id, "proposal_callback", "forbidden", started)
        _answer_callback(client, callback_id, "This action is available only to the bot owner.")
        return
    if is_rate_limited(
        user_id=user_id,
        chat_id=chat_id,
        limit=config.rate_limit_count,
        window_seconds=config.rate_limit_window_seconds,
    ):
        _record_audit(user_id, chat_id, "proposal_callback", "rate_limited", started)
        _answer_callback(client, callback_id, "Too many requests. Please wait a moment.")
        return
    proposal_id, action = proposal_callback
    try:
        proposal_user = profile.user if profile is not None else get_owner(config.owner_email)
        result = apply_callback_action(
            proposal_id=proposal_id,
            action=action,
            user=proposal_user,
            ttl_seconds=config.callback_ttl_seconds,
        )
    except ObjectDoesNotExist:
        result = None
    except Exception as error:
        logger.warning("Telegram proposal callback failed: %s", type(error).__name__)
        result = None

    if result is None:
        _finish_callback(
            client=client,
            callback=callback,
            callback_id=callback_id,
            chat_id=chat_id,
            user_id=user_id,
            command="proposal_callback",
            outcome="failed",
            message="Action failed. Review it in JobApply.",
            started=started,
        )
        return

    _finish_callback(
        client=client,
        callback=callback,
        callback_id=callback_id,
        chat_id=chat_id,
        user_id=user_id,
        command="proposal_callback",
        outcome=result.outcome,
        message=result.message,
        started=started,
    )


def _finish_callback(
    *,
    client: TelegramClient,
    callback: dict[str, Any],
    callback_id: str,
    chat_id: int,
    user_id: int,
    command: str,
    outcome: str,
    message: str,
    started: float,
) -> None:
    _record_audit(user_id, chat_id, command, outcome, started)
    _answer_callback(client, callback_id, message)
    callback_message = callback.get("message") or {}
    message_id = callback_message.get("message_id")
    if message_id is not None:
        try:
            client.edit_message_text(chat_id, int(message_id), message)
        except Exception as error:
            logger.warning("Could not update Telegram callback message: %s", type(error).__name__)


def _answer_callback(client: TelegramClient, callback_id: str, text: str) -> None:
    if not callback_id:
        return
    try:
        client.answer_callback_query(callback_id, text)
    except Exception as error:
        logger.warning("Could not answer Telegram callback: %s", type(error).__name__)


def _record_audit(user_id: int, chat_id: int, command: str, result: str, started: float) -> None:
    try:
        record_command_audit(
            user_id=user_id,
            chat_id=chat_id,
            command=command,
            result=result,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as error:
        logger.warning("Could not record Telegram command audit: %s", type(error).__name__)


def handle_update(update: dict[str, Any], client: TelegramClient, config: TelegramConfig) -> None:
    message = update.get("message") or {}
    text_raw = str(message.get("text", "")).strip()

    if text_raw == "/start disconnected":
        client.send_message(_chat_id(update), "Telegram disconnected from JobApply.")
        return

    if text_raw:
        try:
            profile = bind_telegram_from_start(update)
        except Exception:
            logger.exception("Telegram account binding failed")
            profile = None
        if profile is not None:
            client.send_message(_chat_id(update), "Telegram connected to JobApply.")
            return

    if not is_update_allowed(update, config):
        if (message.get("chat") or {}).get("type") == "private":
            user_id = _user_id(update)
            chat_id = _chat_id(update)
            if is_rate_limited(
                user_id=user_id,
                chat_id=chat_id,
                limit=UNLINKED_REPLY_LIMIT,
                window_seconds=UNLINKED_REPLY_WINDOW_SECONDS,
            ):
                logger.info("Throttled Telegram linking instruction")
                return
            client.send_message(
                chat_id,
                "This Telegram chat is not connected to JobApply yet. Generate a one-time code in Settings → Telegram, then send /link <code> or paste the code here.",
            )
            _record_audit(user_id, chat_id, "link_instruction", "not_linked", time.monotonic())
            return
        logger.warning("Rejected unauthorized Telegram update")
        return

    if update.get("callback_query"):
        _handle_callback(update, client, config)
        return

    profile = None
    if not (
        _chat_id(update) in config.allowed_chat_ids
        and _user_id(update) in config.allowed_user_ids
    ):
        profile = linked_profile_for_update(update)
    data_owner_email = profile.user.email if profile is not None else config.owner_email

    command_parts = text_raw.split(maxsplit=1)
    text = command_parts[0].split("@", 1)[0]
    has_arguments = len(command_parts) > 1
    chat_id = _chat_id(update)
    user_id = _user_id(update)
    started = time.monotonic()
    if is_rate_limited(
        user_id=user_id,
        chat_id=chat_id,
        limit=config.rate_limit_count,
        window_seconds=config.rate_limit_window_seconds,
    ):
        _record_audit(user_id, chat_id, text or "unknown", "rate_limited", started)
        client.send_message(chat_id, "Too many requests. Please wait a moment.")
        return
    reply_markup = None
    result = "ok"

    try:
        with _command_timeout():
            if text in {"/start", "/help"}:
                reply = help_text(config.environment_label, is_admin=_is_owner(user_id, chat_id, config))
            elif text == "/ping":
                reply = "🟢 JobApply bot is online."
            elif text == "/admin":
                if not _is_owner(user_id, chat_id, config):
                    reply = "This command is available only to the bot owner."
                    result = "forbidden"
                else:
                    reply = admin_text()
            elif text == "/status":
                if not _is_owner(user_id, chat_id, config):
                    reply = "This command is available only to the bot owner."
                    result = "forbidden"
                else:
                    reply = status_text(config.environment_label, get_status_snapshot(config.owner_email))
            elif text == "/gmail":
                total, _proposals = get_gmail_summary(data_owner_email)
                assistant_url = _jobapply_url("/gmail_stats/gmail/assistant/")
                reply = gmail_text(total, assistant_url=assistant_url)
                if total:
                    reply_markup = url_keyboard("📨 Open Gmail Assistant", assistant_url)
            elif text == "/applications":
                applications_url = _jobapply_url("/applications/")
                reply = applications_text(
                    get_application_summary(data_owner_email),
                    applications_url=applications_url,
                )
                reply_markup = url_keyboard("📋 Open applications", applications_url)
            elif text == "/health":
                if not _is_owner(user_id, chat_id, config):
                    reply = "This command is available only to the bot owner."
                    result = "forbidden"
                else:
                    reply = health_text(config.environment_label, get_health_snapshot())
            elif text == "/doctor":
                if not _is_owner(user_id, chat_id, config):
                    reply = "This command is available only to the bot owner."
                    result = "forbidden"
                else:
                    reply = doctor_text(config.environment_label, get_doctor_snapshot())
            elif text == "/deploy":
                if has_arguments:
                    reply = "Deploy does not accept branch names or command arguments."
                    result = "invalid"
                elif not _is_owner(user_id, chat_id, config):
                    reply = "This command is available only to the bot owner."
                    result = "forbidden"
                elif not config.deploy_enabled:
                    reply = "Deploy is disabled by configuration."
                    result = "disabled"
                else:
                    deployment = prepare_deploy_request(
                        telegram_user_id=user_id,
                        chat_id=chat_id,
                        branch=config.production_branch,
                        ttl_seconds=config.deploy_confirmation_ttl_seconds,
                    )
                    reply = deployment.message
                    result = deployment.outcome
                    if deployment.request is not None:
                        reply_markup = deploy_keyboard(deployment.request.pk)
            else:
                reply = "Unknown command. Use /help."
    except CommandTimedOut:
        logger.warning("Telegram command timed out: %s", text)
        reply = "Command timed out. Try again later."
        reply_markup = None
        result = "timeout"
    except ObjectDoesNotExist:
        logger.warning("Telegram owner account was not found")
        reply = "JobApply owner account is not configured."
        reply_markup = None
        result = "not_found"
    except Exception as error:
        logger.warning("Telegram command failed: %s", type(error).__name__)
        reply = "Command failed. Check JobApply logs."
        reply_markup = None
        result = "failed"

    client.send_message(chat_id, reply, reply_markup=reply_markup)
    _record_audit(user_id, chat_id, text or "unknown", result, started)
