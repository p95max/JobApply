from __future__ import annotations

import logging
import signal
import time
from contextlib import contextmanager
from typing import Any, Iterator

from django.core.exceptions import ObjectDoesNotExist

from apps.accounts.telegram_linking import bind_telegram_from_start

from .audit import is_rate_limited, record_command_audit
from .client import TelegramClient, telegram_error_detail
from .client_digest import (
    build_client_digest,
    client_digest_keyboard,
    client_digest_text,
    parse_digest_callback,
)
from .config import TelegramConfig
from .deployments import (
    apply_deploy_callback,
    get_deploy_menu,
    parse_deploy_callback,
    parse_deploy_menu_callback,
    prepare_deploy_request,
)
from .diagnostics import get_doctor_snapshot, get_health_snapshot
from .notifications import url_keyboard
from .permissions import is_update_allowed, linked_profile_for_update
from .proposal_actions import apply_callback_action, parse_callback_data
from .selectors import (
    get_ai_usage_digest,
    get_ai_usage_summary,
    get_application_summary,
    get_gmail_summary,
    get_new_users,
    get_owner,
    get_status_snapshot,
)
from apps.site_urls import jobapply_url
from .texts import (
    admin_text,
    ai_usage_digest_text,
    applications_text,
    doctor_text,
    gmail_text,
    health_text,
    help_text,
    new_users_text,
    status_text,
)

logger = logging.getLogger(__name__)
COMMAND_TIMEOUT_SECONDS = 8

CONNECTED_TEXT = (
    "✅ <b>Telegram connected</b>\n\n"
    "This chat is now connected to JobApply."
)
DISCONNECTED_TEXT = (
    "🔌 <b>Telegram disconnected</b>\n\n"
    "This chat is no longer connected to JobApply."
)
NOT_CONNECTED_TEXT = (
    "🔗 <b>Connect Telegram</b>\n\n"
    "This chat is not connected to JobApply yet.\n\n"
    "1. Open <b>Settings → Telegram</b> in JobApply.\n"
    "2. Generate a one-time code.\n"
    "3. Send <code>/link YOUR_CODE</code> here."
)


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


def _is_owner(user_id: int, chat_id: int, config: TelegramConfig) -> bool:
    return (
        config.owner_user_id is not None
        and user_id == config.owner_user_id
        and config.default_chat_id is not None
        and chat_id == config.default_chat_id
    )


def _deploy_confirmation_keyboard(request) -> dict[str, list[list[dict[str, str]]]]:
    confirm_text = "✅ Confirm rollback" if request.operation == "rollback" else "🚀 Confirm deploy"
    return {
        "inline_keyboard": [[
            {"text": confirm_text, "callback_data": f"deploy:{request.pk}:confirm"},
            {"text": "✖️ Cancel", "callback_data": f"deploy:{request.pk}:cancel"},
        ]]
    }


def _handle_callback(update: dict[str, Any], client: TelegramClient, config: TelegramConfig) -> None:
    callback = update.get("callback_query") or {}
    callback_id = str(callback.get("id") or "")
    callback_data = callback.get("data")
    proposal_callback = parse_callback_data(callback_data)
    deploy_callback = parse_deploy_callback(callback_data)
    deploy_menu_operation = parse_deploy_menu_callback(callback_data)
    digest_hours = parse_digest_callback(callback_data)
    if (
        proposal_callback is None
        and deploy_callback is None
        and deploy_menu_operation is None
        and digest_hours is None
    ):
        _answer_callback(client, callback_id, "This action is not available.")
        return

    user_id = _callback_user_id(update)
    chat_id = _callback_chat_id(update)
    started = time.monotonic()

    if digest_hours is not None:
        if not is_update_allowed(update, config):
            _record_audit(user_id, chat_id, "digest_callback", "forbidden", started)
            _answer_callback(client, callback_id, "Connect this Telegram chat to JobApply first.")
            return
        profile = linked_profile_for_update(update)
        if profile is None and not _is_owner(user_id, chat_id, config):
            _record_audit(user_id, chat_id, "digest_callback", "forbidden", started)
            _answer_callback(client, callback_id, "This digest belongs to another JobApply account.")
            return
        if is_rate_limited(
            user_id=user_id,
            chat_id=chat_id,
            limit=config.rate_limit_count,
            window_seconds=config.rate_limit_window_seconds,
        ):
            _record_audit(user_id, chat_id, "digest_callback", "rate_limited", started)
            _answer_callback(client, callback_id, "Too many requests. Please wait a moment.")
            return
        try:
            digest_user = profile.user if profile is not None else get_owner(config.owner_email)
            digest = build_client_digest(user=digest_user, hours=digest_hours)
            client.send_message(
                chat_id,
                client_digest_text(digest, scheduled=False),
                reply_markup=client_digest_keyboard(hours=digest_hours),
            )
            _record_audit(user_id, chat_id, "digest_callback", "ok", started)
            _answer_callback(client, callback_id, "Digest sent.")
        except Exception as error:
            logger.warning("Telegram digest callback failed: %s", type(error).__name__)
            _record_audit(user_id, chat_id, "digest_callback", "failed", started)
            _answer_callback(client, callback_id, "Could not build the digest. Please try again.")
        return

    if deploy_menu_operation is not None:
        if not _is_owner(user_id, chat_id, config):
            _record_audit(user_id, chat_id, "deploy_menu", "forbidden", started)
            _answer_callback(client, callback_id, "This action is available only to the bot owner.")
            return
        if not config.deploy_enabled:
            _record_audit(user_id, chat_id, "deploy_menu", "disabled", started)
            _answer_callback(client, callback_id, "Deploy is disabled by configuration.")
            return
        if is_rate_limited(
            user_id=user_id,
            chat_id=chat_id,
            limit=config.rate_limit_count,
            window_seconds=config.rate_limit_window_seconds,
        ):
            _record_audit(user_id, chat_id, "deploy_menu", "rate_limited", started)
            _answer_callback(client, callback_id, "Too many requests. Please wait a moment.")
            return
        prepared = prepare_deploy_request(
            telegram_user_id=user_id,
            chat_id=chat_id,
            branch=config.production_branch,
            ttl_seconds=config.deploy_confirmation_ttl_seconds,
            operation=deploy_menu_operation,
        )
        message_id = (callback.get("message") or {}).get("message_id")
        try:
            if message_id is not None:
                client.edit_message_text(
                    chat_id,
                    int(message_id),
                    prepared.message,
                    reply_markup=(
                        _deploy_confirmation_keyboard(prepared.request)
                        if prepared.request is not None
                        else None
                    ),
                )
            _record_audit(user_id, chat_id, "deploy_menu", prepared.outcome, started)
            _answer_callback(
                client,
                callback_id,
                "Confirmation required." if prepared.request is not None else prepared.message,
            )
        except Exception as error:
            logger.warning("Telegram deploy menu callback failed: %s", type(error).__name__)
            _record_audit(user_id, chat_id, "deploy_menu", "failed", started)
            _answer_callback(client, callback_id, "Could not prepare production operation.")
        return

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
            logger.warning("Could not update Telegram callback message: %s", telegram_error_detail(error))


def _answer_callback(client: TelegramClient, callback_id: str, text: str) -> None:
    if not callback_id:
        return
    try:
        client.answer_callback_query(callback_id, text)
    except Exception as error:
        logger.warning("Could not answer Telegram callback: %s", telegram_error_detail(error))


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
        client.send_message(_chat_id(update), DISCONNECTED_TEXT)
        return

    if text_raw:
        try:
            profile = bind_telegram_from_start(update)
        except Exception:
            logger.exception("Telegram account binding failed")
            profile = None
        if profile is not None:
            client.send_message(_chat_id(update), CONNECTED_TEXT)
            return

    if not is_update_allowed(update, config):
        if (message.get("chat") or {}).get("type") == "private":
            user_id = _user_id(update)
            chat_id = _chat_id(update)
            client.send_message(chat_id, NOT_CONNECTED_TEXT)
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
        client.send_message(chat_id, "⏳ <b>Too many requests</b>\n\nPlease wait a moment and try again.")
        return
    reply_markup = None
    result = "ok"

    try:
        with _command_timeout():
            if text in {"/start", "/help"}:
                reply = help_text(config.environment_label, is_admin=_is_owner(user_id, chat_id, config))
                reply += "\n📊 /digest — your JobApply activity for the last 24 hours"
            elif text == "/ping":
                reply = "🟢 <b>JobApply bot is online</b>"
            elif text == "/digest":
                if has_arguments:
                    reply = "⚠️ <b>Invalid command</b>\n\n<code>/digest</code> does not accept arguments."
                    result = "invalid"
                else:
                    digest_user = profile.user if profile is not None else get_owner(config.owner_email)
                    digest = build_client_digest(user=digest_user, hours=24)
                    reply = client_digest_text(digest, scheduled=False)
                    reply_markup = client_digest_keyboard(hours=24)
            elif text == "/admin":
                if not _is_owner(user_id, chat_id, config):
                    reply = "⛔ <b>Access denied</b>\n\nThis command is available only to the bot owner."
                    result = "forbidden"
                else:
                    reply = admin_text()
            elif text == "/status":
                if not _is_owner(user_id, chat_id, config):
                    reply = "⛔ <b>Access denied</b>\n\nThis command is available only to the bot owner."
                    result = "forbidden"
                else:
                    reply = status_text(config.environment_label, get_status_snapshot(config.owner_email))
            elif text == "/aiusage":
                if has_arguments:
                    reply = "⚠️ <b>Invalid command</b>\n\n<code>/aiusage</code> does not accept arguments."
                    result = "invalid"
                elif not _is_owner(user_id, chat_id, config):
                    reply = "⛔ <b>Access denied</b>\n\nThis command is available only to the bot owner."
                    result = "forbidden"
                else:
                    report_url = jobapply_url("/reports/ai-statistics/")
                    reply = ai_usage_digest_text(get_ai_usage_digest(hours=24), scheduled=False)
                    reply_markup = url_keyboard("📊 Open AI statistics", report_url)
            elif text == "/newusers":
                if not _is_owner(user_id, chat_id, config):
                    reply = "⛔ <b>Access denied</b>\n\nThis command is available only to the bot owner."
                    result = "forbidden"
                elif has_arguments:
                    reply = "⚠️ <b>Invalid command</b>\n\n<code>/newusers</code> does not accept arguments."
                    result = "invalid"
                else:
                    reply = new_users_text(get_new_users(days=7), days=7)
            elif text == "/gmail":
                total, _proposals = get_gmail_summary(data_owner_email)
                ai_usage = get_ai_usage_summary(data_owner_email)
                assistant_url = jobapply_url("/gmail_stats/gmail/assistant/")
                reply = gmail_text(total, ai_usage=ai_usage, assistant_url=assistant_url)
                if total:
                    reply_markup = url_keyboard("📨 Open Gmail Assistant", assistant_url)
            elif text == "/applications":
                applications_url = jobapply_url("/applications/")
                reply = applications_text(
                    get_application_summary(data_owner_email),
                    applications_url=applications_url,
                )
                reply_markup = url_keyboard("📋 Open applications", applications_url)
            elif text == "/health":
                if not _is_owner(user_id, chat_id, config):
                    reply = "⛔ <b>Access denied</b>\n\nThis command is available only to the bot owner."
                    result = "forbidden"
                else:
                    reply = health_text(config.environment_label, get_health_snapshot())
            elif text == "/doctor":
                if not _is_owner(user_id, chat_id, config):
                    reply = "⛔ <b>Access denied</b>\n\nThis command is available only to the bot owner."
                    result = "forbidden"
                else:
                    reply = doctor_text(config.environment_label, get_doctor_snapshot())
            elif text == "/deploy":
                if has_arguments:
                    reply = "⚠️ <b>Invalid command</b>\n\n<code>/deploy</code> does not accept branch names or arguments."
                    result = "invalid"
                elif not _is_owner(user_id, chat_id, config):
                    reply = "⛔ <b>Access denied</b>\n\nThis command is available only to the bot owner."
                    result = "forbidden"
                elif not config.deploy_enabled:
                    reply = "⚠️ <b>Deploy disabled</b>\n\nProduction deploy is disabled by configuration."
                    result = "disabled"
                else:
                    menu = get_deploy_menu(config.production_branch)
                    if menu is None:
                        reply = "❌ <b>Production control unavailable</b>\n\nCould not read Git commits."
                        result = "failed"
                    else:
                        rollback = menu.rollback_commit[:12] if menu.rollback_commit else "not available yet"
                        reply = (
                            "🚀 <b>Production control</b>\n\n"
                            f"Current: <code>{menu.current_commit}</code>\n"
                            f"Latest master: <code>{menu.latest_commit[:12]}</code>\n"
                            f"Rollback target: <code>{rollback}</code>\n\n"
                            "Choose an operation. A separate confirmation is required."
                        )
                        reply_markup = {
                            "inline_keyboard": [
                                [{"text": "🚀 Deploy latest", "callback_data": "deploymenu:deploy"}],
                                [{"text": "↩️ Rollback last successful", "callback_data": "deploymenu:rollback"}],
                            ]
                        }
            else:
                reply = "❓ <b>Unknown command</b>\n\nUse <code>/help</code> to see available commands."
    except CommandTimedOut:
        logger.warning("Telegram command timed out: %s", text)
        reply = "⏱ <b>Command timed out</b>\n\nPlease try again in a moment."
        reply_markup = None
        result = "timeout"
    except ObjectDoesNotExist:
        logger.warning("Telegram owner account was not found")
        reply = "⚠️ <b>Account unavailable</b>\n\nThe JobApply owner account is not configured."
        reply_markup = None
        result = "not_found"
    except Exception as error:
        logger.warning("Telegram command failed: %s", type(error).__name__)
        reply = "❌ <b>Command failed</b>\n\nPlease try again. If the problem continues, check JobApply logs."
        reply_markup = None
        result = "failed"

    client.send_message(chat_id, reply, reply_markup=reply_markup)
    _record_audit(user_id, chat_id, text or "unknown", result, started)
