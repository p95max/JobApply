from __future__ import annotations

from html import escape

from allauth.account.signals import user_signed_up
from django.contrib.auth.signals import user_logged_out
from django.db import transaction
from django.dispatch import receiver

from apps.telegram_bot.notifications import send_notification_once


@receiver(user_logged_out)
def clear_turnstile_flag_on_logout(sender, request, user, **kwargs):
    if request and hasattr(request, "session"):
        request.session.pop("turnstile_passed", None)
        request.session.modified = True


@receiver(user_signed_up)
def notify_admin_about_new_user(sender, request, user, **kwargs):
    email = (getattr(user, "email", "") or "").strip()
    if not email:
        return

    text = (
        "👤 <b>New JobApply user</b>\n\n"
        f"📧 Email: <code>{escape(email)}</code>"
    )
    event_key = f"new_user:{user.pk}"

    transaction.on_commit(
        lambda: send_notification_once(
            event_key=event_key,
            event_type="new_user",
            text=text,
        )
    )
