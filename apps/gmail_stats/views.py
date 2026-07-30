from __future__ import annotations

from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from apps.gmail_stats.services.credentials import get_google_credentials_for_user
from apps.gmail_stats.services.gmail_client import GmailClient
from apps.gmail_stats.services.sync import sync_gmail_messages_for_user
from apps.gmail_stats.models import GmailMessage, GmailSyncState


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

    qs = GmailMessage.objects.filter(user=request.user, received_at__gte=since)

    qs = qs.exclude(direction="outbound")
    responses = qs.exclude(detected_type__in=["unknown", "noise"]).count()
    rejections = qs.filter(detected_type="rejection").count()
    invites = qs.filter(detected_type="invite").count()
    auto_ack = qs.filter(detected_type="auto_ack").count()

    state = GmailSyncState.objects.filter(user=request.user).first()
    last_synced_at = state.last_synced_at.isoformat() if state and state.last_synced_at else None

    return JsonResponse({
        "days": days,
        "responses": responses,
        "rejections": rejections,
        "invites": invites,
        "auto_ack": auto_ack,
        "last_synced_at": last_synced_at,
    })


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

    creds = get_google_credentials_for_user(request.user)
    if not creds:
        return JsonResponse(
            {"error": "Google Gmail not connected. Reconnect Google with gmail.readonly scope."},
            status=403,
        )

    gmail = GmailClient(creds)

    try:
        gmail.list_message_ids(query=f"newer_than:{min(days, 7)}d", max_results=1)
    except RuntimeError as e:
        msg = str(e)
        if "accessNotConfigured" in msg or "Gmail API has not been used" in msg:
            return JsonResponse(
                {"error": "Gmail API is disabled for your Google Cloud project. Enable Gmail API in Google Cloud Console and retry."},
                status=403,
            )
        if "insufficientPermissions" in msg:
            return JsonResponse(
                {"error": "Missing permission (gmail.readonly). Reconnect Google and grant Gmail access."},
                status=403,
            )
        return JsonResponse({"error": f"Gmail access failed: {msg}"}, status=403)
    except Exception as e:
        return JsonResponse({"error": f"Gmail access failed: {e}"}, status=403)

    res = sync_gmail_messages_for_user(
        user=request.user,
        gmail_client=gmail,
        days=days,
        max_results_each=500,
    )
    return JsonResponse({"ok": True, "result": res})

