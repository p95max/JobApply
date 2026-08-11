from __future__ import annotations

import logging
import secrets
from urllib.parse import quote

from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.google.views import oauth2_login
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.gmail_stats.models import GmailSyncState
from apps.gmail_stats.services.credentials import get_google_credentials_for_user
from apps.security.turnstile import verify_turnstile
from apps.telegram_bot.notifications import send_notification_once

from .demo_limits import DemoStartRateLimitError, claim_demo_start, client_ip
from .models import TelegramLinkTokenCooldownError, UserProfile

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


def _is_demo_user(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and UserProfile.objects.filter(user=user, is_demo_user=True).exists()
    )


@require_POST
def start_demo(request):
    """Create an isolated, temporary workspace without a Google account."""
    if request.user.is_authenticated:
        return redirect("dashboard")

    try:
        turnstile = verify_turnstile(
            request.POST.get("cf-turnstile-response", ""),
            remote_ip=request.META.get("REMOTE_ADDR"),
        )
    except Exception:
        logger.warning("Demo Turnstile verification failed with an upstream error", exc_info=True)
        messages.error(request, "Security check could not be verified. Please try again.")
        return redirect("landing")

    if not turnstile.success:
        messages.error(request, "Complete the security check before starting the demo.")
        return redirect("landing")

    try:
        claim_demo_start(ip_address=client_ip(request))
    except DemoStartRateLimitError as error:
        messages.error(
            request,
            f"Too many demo starts from this network. Please try again in {error.retry_after_seconds} seconds.",
        )
        return redirect("landing")

    while True:
        username = f"demo-{secrets.token_urlsafe(8)}"
        if not User.objects.filter(username=username).exists():
            break

    ttl_hours = int(getattr(settings, "DEMO_ACCOUNT_TTL_HOURS", 12))
    with transaction.atomic():
        user = User.objects.create_user(username=username)
        UserProfile.objects.create(user=user, is_demo_user=True)
        transaction.on_commit(
            lambda: send_notification_once(
                event_key=f"demo_started:{user.pk}",
                event_type="demo_started",
                text=(
                    "🧪 <b>Demo mode started</b>\n\n"
                    f"👤 Workspace: <code>{user.username}</code>\n"
                    f"⏳ Auto-delete after: <b>{ttl_hours} hours</b>"
                ),
            )
        )

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.set_expiry(60 * 60 * ttl_hours)
    messages.info(
        request,
        (
            "Demo mode is active. Sign in with Google to unlock connected services. "
            f"This temporary demo account and its data will be automatically deleted after {ttl_hours} hours."
        ),
    )
    return redirect("dashboard")


@require_POST
def start_full_login(request):
    """Leave a demo workspace before starting a real Google OAuth session."""
    if _is_demo_user(request.user):
        logout(request)
    return redirect("/accounts/google/login/?next=/dashboard/")


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
                messages.error(request, "Could not save consent. Try again later.")

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
    link_command = ""
    telegram_link_url = ""
    if profile.telegram_link_token_expires_at and profile.telegram_link_token_expires_at > timezone.now():
        link_command = request.session.get("telegram_link_command", "")
        telegram_link_url = request.session.get("telegram_link_url", "")
    else:
        request.session.pop("telegram_link_command", None)
        request.session.pop("telegram_link_url", None)
    bot_username = str(getattr(settings, "TELEGRAM_BOT_USERNAME", "")).strip().lstrip("@")
    telegram_bot_url = f"https://t.me/{bot_username}" if bot_username else ""

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "telegram_link":
            try:
                token = profile.create_telegram_link_token()
            except TelegramLinkTokenCooldownError:
                messages.info(request, "A Telegram connection code was requested recently. Please wait a minute.")
                return redirect("accounts:settings")
            link_command = f"/link {token}"
            telegram_link_url = f"{telegram_bot_url}?start={quote(token)}" if telegram_bot_url else ""
            request.session["telegram_link_command"] = link_command
            request.session["telegram_link_url"] = telegram_link_url
            messages.info(request, "Telegram link is valid for 15 minutes.")
            return redirect("accounts:settings")
        if action == "telegram_disconnect":
            profile.clear_telegram_link()
            request.session.pop("telegram_link_command", None)
            request.session.pop("telegram_link_url", None)
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

    active_tab = request.GET.get("tab", "telegram")
    if active_tab not in {"telegram", "gmail", "account"}:
        active_tab = "telegram"

    return render(
        request,
        "accounts/settings.html",
        {
            "profile": profile,
            "active_tab": active_tab,
            "telegram_bot_username": bot_username,
            "telegram_bot_url": telegram_bot_url,
            "telegram_link_command": link_command,
            "telegram_link_url": telegram_link_url,
            "gmail_connected": gmail_connected,
            "gmail_email": gmail_email,
            "gmail_last_synced_at": sync_state.last_synced_at if sync_state else None,
            "gmail_interval_hours": max(1, interval_seconds // 3600),
            "gmail_safe_error": gmail_error,
        },
    )


@login_required
def delete_account(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    user = request.user
    with transaction.atomic():
        user.delete()
    logout(request)
    messages.success(request, "Your JobApply account and its associated data were deleted.")
    return redirect("landing")
