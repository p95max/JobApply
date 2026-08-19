from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from apps.gmail_assistant.models import GmailAnalysis, GmailEventType
from apps.gmail_assistant.services.dev_tools import has_dev_tools_access
from apps.gmail_assistant.services.sync import sync_gmail_messages_for_user
from apps.gmail_stats.models import GmailDirection, GmailSyncState
from apps.gmail_stats.services.credentials import get_google_credentials_for_user
from apps.gmail_stats.services.gmail_client import GmailClient
from apps.gmail_stats.services.sync_control import GmailSyncBusyError, GmailSyncCooldownError, claim_manual_sync_slot

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
    analyses = GmailAnalysis.objects.filter(
        user=request.user,
        message__received_at__gte=since,
        message__direction=GmailDirection.INBOUND,
        is_job_related=True,
    )
    state = GmailSyncState.objects.filter(user=request.user).first()

    invitation_types = {
        GmailEventType.INTERVIEW_INVITATION,
        GmailEventType.INTERVIEW_RESCHEDULED,
        GmailEventType.SCREENING,
    }
    acknowledgement_types = {
        GmailEventType.APPLICATION_CONFIRMATION_REQUIRED,
        GmailEventType.APPLICATION_SENT,
        GmailEventType.APPLICATION_RECEIVED,
    }

    return JsonResponse(
        {
            "days": days,
            "job_related_emails": analyses.count(),
            "rejections": analyses.filter(event_type=GmailEventType.REJECTION).count(),
            "invites": analyses.filter(event_type__in=invitation_types).count(),
            "auto_ack": analyses.filter(event_type__in=acknowledgement_types).count(),
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
    reanalyze_existing = request.GET.get("reanalyze", "0") == "1"
    reanalyze_today_only = request.GET.get("today_only", "0") == "1"
    include_sent = request.GET.get("include_sent", "0") == "1"
    if (reanalyze_existing or reanalyze_today_only) and not has_dev_tools_access(user=request.user):
        return JsonResponse({"error": "Not found"}, status=404)
    if reanalyze_today_only and not reanalyze_existing:
        return JsonResponse({"error": "today_only requires reanalyze=1"}, status=400)

    # Dev Tools reanalysis is explicitly a full investigation pass for the
    # selected period. Include Sent so direct applications are rediscovered and
    # reclassified together with inbound recruiter mail. Automatic sync is
    # unaffected because reanalysis is restricted to the configured dev owner.
    if reanalyze_existing:
        include_sent = True

    # The configured development owner may deliberately rerun a sync while
    # investigating an email. The per-user execution lock below still prevents
    # overlapping Google/API work; only the manual-button cooldown is bypassed.
    if not has_dev_tools_access(user=request.user):
        try:
            claim_manual_sync_slot(user=request.user)
        except GmailSyncCooldownError as error:
            return JsonResponse(
                {
                    "error": "Gmail sync was requested recently. Please wait before trying again.",
                    "retry_after_seconds": error.retry_after_seconds,
                },
                status=429,
            )

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
        result = sync_gmail_messages_for_user(
            user=request.user,
            gmail_client=gmail,
            days=days,
            max_results_each=500,
            reanalyze_existing=reanalyze_existing,
            reanalyze_today_only=reanalyze_today_only,
            include_sent=include_sent,
        )
    except GmailSyncBusyError:
        return JsonResponse(
            {"error": "A Gmail sync is already running for this account."},
            status=409,
        )
    except (RuntimeError, ValueError) as error:
        logger.warning("Gmail sync failed user_id=%s error=%s", request.user.id, type(error).__name__)
        return JsonResponse({"error": "Gmail sync failed. Try again later."}, status=502)
    return JsonResponse({"ok": True, "result": result})
