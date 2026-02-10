from __future__ import annotations

from apps.gmail_stats.models import GmailMessage

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone

from apps.gmail_stats.services.credentials import get_google_credentials_for_user
from apps.gmail_stats.services.gmail_client import GmailClient
from apps.gmail_stats.services.sync import sync_gmail_messages_for_user



@login_required
def gmail_stats(request):
    days = int(request.GET.get("days", "180"))
    since = timezone.now() - timedelta(days=days)

    qs = GmailMessage.objects.filter(user=request.user, received_at__gte=since)

    responses = qs.exclude(detected_type__in=["unknown", "noise"]).count()
    rejections = qs.filter(detected_type="rejection").count()
    invites = qs.filter(detected_type="invite").count()
    auto_ack = qs.filter(detected_type="auto_ack").count()

    return JsonResponse(
        {
            "days": days,
            "responses": responses,
            "rejections": rejections,
            "invites": invites,
            "auto_ack": auto_ack,
        }
    )

@login_required
def gmail_sync_view(request):
    days = int(request.GET.get("days", "180"))

    creds = get_google_credentials_for_user(request.user)
    if not creds:
        return JsonResponse(
            {"error": "Google Gmail not connected (missing token or refresh token). Reconnect Google with gmail.readonly scope."},
            status=403,
        )

    gmail = GmailClient(creds)

    try:
        gmail.list_message_ids(query=f"newer_than:{min(days, 7)}d", max_results=1)
    except Exception as e:
        return JsonResponse(
            {"error": f"Gmail access failed: {e}. Usually means missing gmail.readonly scope -> reconnect."},
            status=403,
        )

    res = sync_gmail_messages_for_user(
        user=request.user,
        gmail_client=gmail,
        days=days,
        max_results_each=500,
    )
    return JsonResponse({"ok": True, "result": res})

