from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from allauth.socialaccount.models import SocialToken

from apps.applications.models import ApplicationStatus, JobApplication
from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailAssistantSettings,
    ProposalStatus,
)
from apps.interviews.models import InterviewEvent, InterviewStatus
from apps.reports.drive import get_drive_status
from apps.reports.models import CloudBackupSettings

from .models import UserProfile


@login_required
def dashboard(request):
    now = timezone.now()
    applications = JobApplication.objects.filter(user=request.user)
    active_applications = applications.exclude(
        status__in=(ApplicationStatus.REJECTED, ApplicationStatus.ARCHIVED)
    )
    follow_up_due_applications = applications.filter(
        status=ApplicationStatus.APPLIED,
        recruiter_reply_at__isnull=True,
        applied_at__lt=now - timedelta(days=14),
    )
    upcoming_interviews = (
        InterviewEvent.objects.filter(
            user=request.user,
            status=InterviewStatus.SCHEDULED,
            starts_at__gte=now,
        )
        .select_related("application")
        .order_by("starts_at")
    )
    pending_proposals = (
        ApplicationUpdateProposal.objects.filter(
            user=request.user,
            status=ProposalStatus.PENDING,
        )
        .select_related("message", "analysis", "application")
        .order_by("-created_at")
    )
    accepted_proposals = (
        ApplicationUpdateProposal.objects.filter(
            user=request.user,
            status=ProposalStatus.ACCEPTED,
        )
        .select_related("message", "analysis", "application")
        .order_by("-reviewed_at", "-updated_at")
    )
    assistant_settings = GmailAssistantSettings.objects.filter(user=request.user).first()
    profile = UserProfile.objects.filter(user=request.user).only("telegram_chat_id").first()
    drive_status = get_drive_status(request.user)
    backup_settings = CloudBackupSettings.objects.filter(user=request.user).only("enabled").first()
    drive_connected = bool(drive_status.get("connected") and drive_status.get("has_refresh_token"))
    gmail_connected = SocialToken.objects.filter(
        account__user=request.user,
        account__provider="google",
    ).exclude(token="").exists()

    return render(
        request,
        "accounts/dashboard.html",
        {
            "active_application_count": active_applications.count(),
            "applications_this_week": applications.filter(
                created_at__gte=now - timedelta(days=7)
            ).count(),
            "follow_up_due_count": follow_up_due_applications.count(),
            "next_interview": upcoming_interviews.first(),
            "recent_applications": applications.order_by("-updated_at")[:5],
            "pending_proposal_count": pending_proposals.count(),
            "pending_proposals": pending_proposals[:5],
            "accepted_proposal_count": accepted_proposals.count(),
            "accepted_proposals": accepted_proposals[:5],
            "gmail_assistant_active": bool(
                assistant_settings and assistant_settings.ai_enabled
            ),
            "gmail_last_run_at": (
                assistant_settings.last_successful_run_at
                if assistant_settings
                else None
            ),
            "telegram_connected": bool(profile and profile.telegram_chat_id),
            "gmail_connected": gmail_connected,
            "drive_connected": drive_connected,
            "drive_auto_backup_enabled": bool(backup_settings and backup_settings.enabled),
        },
    )
