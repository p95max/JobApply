from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.applications.models import ApplicationStatus, JobApplication
from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailAssistantSettings,
    ProposalStatus,
)
from apps.interviews.models import InterviewEvent, InterviewStatus


@login_required
def dashboard(request):
    now = timezone.now()
    applications = JobApplication.objects.filter(user=request.user)
    active_applications = applications.exclude(
        status__in=(ApplicationStatus.REJECTED, ApplicationStatus.ARCHIVED)
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
    assistant_settings = GmailAssistantSettings.objects.filter(user=request.user).first()

    return render(
        request,
        "accounts/dashboard.html",
        {
            "active_application_count": active_applications.count(),
            "applications_this_week": applications.filter(
                created_at__gte=now - timedelta(days=7)
            ).count(),
            "upcoming_interview_count": upcoming_interviews.count(),
            "next_interview": upcoming_interviews.first(),
            "recent_applications": applications.order_by("-updated_at")[:5],
            "pending_proposal_count": pending_proposals.count(),
            "pending_proposals": pending_proposals[:5],
            "gmail_assistant_active": bool(
                assistant_settings and assistant_settings.ai_enabled
            ),
            "gmail_last_run_at": (
                assistant_settings.last_successful_run_at
                if assistant_settings
                else None
            ),
        },
    )
