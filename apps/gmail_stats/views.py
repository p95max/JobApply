from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from apps.gmail_assistant.services.sync import sync_gmail_messages_for_user
from apps.gmail_stats.models import GmailMessage, GmailSyncState
from apps.gmail_stats.services.credentials import get_google_credentials_for_user
from apps.gmail_stats.services.gmail_client import GmailClient

logger = logging.getLogger(__name__)


@login_required
def gmail_dashboard(request):
    return render(request, "gmail_stats/dashboard.html")


@login_required
def gmail_stats_api(request):
    try:
        days = int(request.GET.get("days", "180"))
    except ValueError:
        return JsonResponse({"error": "days must be an integer"}, status=400)
    if not 1 <= days <= 365:
        return JsonResponse({"error": "days must be between 1 and 365"}, status=400)
    since = timezone.now() - timedelta(days=days)
    messages = GmailMessage.objects.filter(user=request.user, received_at__gte=since).exclude(direction="outbound")
    state = GmailSyncState.objects.filter(user=request.user).first()
    return JsonResponse(
        {
            "days": days,
            "responses": messages.exclude(detected_type__in=["unknown", "noise"]).count(),
            "rejections": messages.filter(detected_type="rejection").count(),
            "invites": messages.filter(detected_type="invite").count(),
            "auto_ack": messages.filter(detected_type="auto_ack").count(),
            "last_synced_at": state.last_synced_at.isoformat() if state and state.last_synced_at else None,
        }
    )


@login_required
def gmail_sync_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    try:
        days = int(request.GET.get("days", "180"))
    except ValueError:
        return JsonResponse({"error": "days must be an integer"}, status=400)
    if not 1 <= days <= 365:
        return JsonResponse({"error": "days must be between 1 and 365"}, status=400)

    try:
        credentials = get_google_credentials_for_user(request.user)
    except (RuntimeError, ValueError) as error:
        logger.warning("Gmail credential lookup failed user_id=%s error=%s", request.user.id, type(error).__name__)
        return JsonResponse({"error": "Google Gmail connection needs attention. Reconnect Google and try again."}, status=403)
    if not credentials:
        return JsonResponse({"error": "Google Gmail not connected. Reconnect Google with gmail.readonly scope."}, status=403)

    gmail = GmailClient(credentials)
    try:
        gmail.list_message_ids(query=f"newer_than:{min(days, 7)}d", max_results=1)
    except RuntimeError as error:
        detail = str(error)
        if "accessNotConfigured" in detail or "Gmail API has not been used" in detail:
            return JsonResponse({"error": "Gmail API is disabled for your Google Cloud project. Enable Gmail API in Google Cloud Console and retry."}, status=403)
        if "insufficientPermissions" in detail:
            return JsonResponse({"error": "Missing permission (gmail.readonly). Reconnect Google and grant Gmail access."}, status=403)
        logger.warning("Gmail preflight failed user_id=%s error=%s", request.user.id, type(error).__name__)
        return JsonResponse({"error": "Gmail access failed. Reconnect Google and try again."}, status=403)
    except (AttributeError, TypeError, ValueError) as error:
        logger.warning("Gmail preflight failed user_id=%s error=%s", request.user.id, type(error).__name__)
        return JsonResponse({"error": "Gmail access failed. Reconnect Google and try again."}, status=403)

    try:
        result = sync_gmail_messages_for_user(user=request.user, gmail_client=gmail, days=days, max_results_each=500)
    except (RuntimeError, ValueError) as error:
        logger.warning("Gmail sync failed user_id=%s error=%s", request.user.id, type(error).__name__)
        return JsonResponse({"error": "Gmail sync failed. Try again later."}, status=502)
    return JsonResponse({"ok": True, "result": result})
