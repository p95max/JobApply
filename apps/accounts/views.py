from __future__ import annotations

import logging
from urllib.parse import quote

from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.google.views import oauth2_login
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import redirect, render

from apps.gmail_stats.models import GmailSyncState
from apps.gmail_stats.services.credentials import get_google_credentials_for_user

from .models import UserProfile

logger = logging.getLogger(__name__)


def ensure_profile(user: User) -> UserProfile:
    try:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile
    except Exception:
        logger.exception("ensure_profile failed user=%s", getattr(user, "id", None))
        raise


def root(request):
    if request.user.is_authenticated:
        return redirect("/applications/")
    try:
        return oauth2_login(request)
    except Exception:
        logger.exception("root oauth2_login failed")
        return redirect("/accounts/login/")


@login_required
def consent(request):
    try:
        profile = ensure_profile(request.user)
    except Exception:
        messages.error(request, "Could not load your profile. Try again later.")
        return redirect("/")

    if request.method == "POST":
        accepted = bool(request.POST.get("consent"))
        if accepted:
            try:
                profile.accept_consent()
                messages.success(request, "Consent saved.")
                return redirect("applications:list")
            except Exception:
                logger.exception("accept_consent failed user=%s", request.user.id)
                messages.error(request, "Could not save consent. Try again.")

    return render(
        request,
        "accounts/consent.html",
        {
            "profile": profile,
            "consent_text_1": "I agree to provide access to my Google account for authentication purposes.",
            "consent_text_2": "Administration is not responsible for storing personal data beyond reasonable security measures.",
        },
    )


@login_required
def settings_view(request):
    profile = ensure_profile(request.user)
    link_command = request.session.pop("telegram_link_command", "")
    telegram_link_url = request.session.pop("telegram_link_url", "")

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "telegram_link":
            token = profile.create_telegram_link_token()
            link_command = f"/start {token}"
            bot_username = str(getattr(settings, "TELEGRAM_BOT_USERNAME", "")).strip().lstrip("@")
            telegram_link_url = f"https://t.me/{bot_username}?start={quote(token)}" if bot_username else ""
            request.session["telegram_link_command"] = link_command
            request.session["telegram_link_url"] = telegram_link_url
            messages.info(request, "Telegram link is valid for 15 minutes.")
            return redirect("accounts:settings")
        if action == "telegram_disconnect":
            profile.clear_telegram_link()
            messages.success(request, "Telegram disconnected.")
            return redirect("accounts:settings")

    google_account = SocialAccount.objects.filter(user=request.user, provider="google").first()
    gmail_email = request.user.email or ""
    if google_account and google_account.extra_data:
        gmail_email = google_account.extra_data.get("email") or gmail_email

    gmail_connected = False
    gmail_error = ""
    try:
        gmail_connected = bool(get_google_credentials_for_user(request.user))
    except Exception as error:
        gmail_error = type(error).__name__

    sync_state = GmailSyncState.objects.filter(user=request.user).first()
    interval_seconds = int(getattr(settings, "GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS", 21600))

    return render(
        request,
        "accounts/settings.html",
        {
            "profile": profile,
            "active_tab": request.GET.get("tab", "telegram"),
            "telegram_link_command": link_command,
            "telegram_link_url": telegram_link_url,
            "gmail_connected": gmail_connected,
            "gmail_email": gmail_email,
            "gmail_last_synced_at": sync_state.last_synced_at if sync_state else None,
            "gmail_interval_hours": max(1, interval_seconds // 3600),
            "gmail_safe_error": gmail_error,
        },
    )
