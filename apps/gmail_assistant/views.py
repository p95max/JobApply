from __future__ import annotations

import logging
import re
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.applications.models import JobApplication
from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailAssistantSettings,
    GmailEventType,
    ProposalStatus,
)
from apps.gmail_assistant.services.ai_policy import AIUsagePolicy
from apps.gmail_assistant.services.application_matcher import match_for_message
from apps.gmail_assistant.services.apply_proposal import ProposalApplyError, apply_proposal, review_proposal
from apps.gmail_assistant.services.dev_tools import has_dev_tools_access
from apps.gmail_assistant.services.reset import reset_gmail_assistant_data

logger = logging.getLogger(__name__)


def _event_tone(event_type: str) -> str:
    if event_type == GmailEventType.REJECTION:
        return "danger"
    if event_type in {GmailEventType.INTERVIEW_INVITATION, GmailEventType.INTERVIEW_RESCHEDULED}:
        return "success"
    if event_type == GmailEventType.OFFER:
        return "warning"
    if event_type in {
        GmailEventType.APPLICATION_CONFIRMATION_REQUIRED,
        GmailEventType.APPLICATION_SENT,
        GmailEventType.APPLICATION_RECEIVED,
    }:
        return "primary"
    return "secondary"


def _first_url(*values: object) -> str:
    for value in values:
        if isinstance(value, str):
            match = re.search(r"https?://[^\s<>()]+", value)
            if match:
                return match.group(0).rstrip(".,;:!?")
    return ""


def _group_proposals_by_message(proposals):
    grouped = []
    groups_by_message_id = {}
    for proposal in proposals:
        group = groups_by_message_id.get(proposal.message_id)
        if group is None:
            group = {
                "message": proposal.message,
                "analysis": proposal.analysis,
                "representative": proposal,
                "proposals": [],
            }
            groups_by_message_id[proposal.message_id] = group
            grouped.append(group)
        group["proposals"].append(proposal)
    return grouped


@login_required
def gmail_assistant(request):
    proposal_queryset = (
        ApplicationUpdateProposal.objects.filter(user=request.user)
        .select_related("message", "analysis", "application")
        .order_by("-message__received_at", "-created_at")
    )
    try:
        selected_status = ProposalStatus(request.GET.get("status", ProposalStatus.PENDING))
    except ValueError:
        selected_status = ProposalStatus.PENDING
    proposals = list(proposal_queryset.filter(status=selected_status.value)[:150])
    proposal_groups = _group_proposals_by_message(proposals)[:50]
    proposal_counts = {
        proposal_status: proposal_queryset.filter(status=proposal_status).count()
        for proposal_status in ProposalStatus.values
    }
    assistant_settings, _created = GmailAssistantSettings.objects.get_or_create(user=request.user)
    ai_policy = AIUsagePolicy.from_environment()
    ai_daily_used = ai_policy.daily_usage(user=request.user)
    ai_daily_remaining = max(0, ai_policy.daily_limit - ai_daily_used)
    next_automatic_check_at = None
    if (
        django_settings.GMAIL_ASSISTANT_AUTO_SYNC_ENABLED
        and assistant_settings.ai_enabled
        and assistant_settings.last_successful_run_at
        and not assistant_settings.last_error_message
    ):
        next_automatic_check_at = assistant_settings.last_successful_run_at + timedelta(
            seconds=django_settings.GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS
        )
    return render(
        request,
        "gmail_assistant/assistant.html",
        {
            "proposal_groups": proposal_groups,
            "selected_status": selected_status.value,
            "proposal_status_filters": [
                {"value": value, "label": label, "count": proposal_counts[value]}
                for value, label in ProposalStatus.choices
            ],
            "settings": assistant_settings,
            "pending_count": proposal_counts[ProposalStatus.PENDING],
            "technical_event_types": {
                GmailEventType.APPLICATION_CONFIRMATION_REQUIRED,
                GmailEventType.APPLICATION_SENT,
                GmailEventType.APPLICATION_RECEIVED,
            },
            "interview_event_types": {
                GmailEventType.INTERVIEW_INVITATION,
                GmailEventType.INTERVIEW_RESCHEDULED,
            },
            "auto_sync_interval_minutes": django_settings.GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS // 60,
            "next_automatic_check_at": next_automatic_check_at,
            "dev_tools_enabled": has_dev_tools_access(user=request.user),
            "ai_model_name": django_settings.OPENAI_EMAIL_MODEL,
            "ai_daily_limit": ai_policy.daily_limit,
            "ai_daily_used": ai_daily_used,
            "ai_daily_remaining": ai_daily_remaining,
            "ai_confidence_threshold": django_settings.GMAIL_ASSISTANT_AI_CONFIDENCE_THRESHOLD,
        },
    )


@login_required
def gmail_proposal_detail(request, pk: int):
    proposal = get_object_or_404(
        ApplicationUpdateProposal.objects.select_related("message", "analysis", "application"),
        pk=pk,
        user=request.user,
    )
    candidates = list(
        JobApplication.objects.filter(user=request.user)
        .exclude(status__in=["archived", "rejected"])
        .order_by("-updated_at", "-pk")
    )
    match = match_for_message(user=request.user, message=proposal.message, extracted_data=proposal.analysis.extracted_data)
    action = proposal.changes.get("action") if isinstance(proposal.changes.get("action"), dict) else {}
    review_context = {
        "sender_domain": proposal.message.from_email.rsplit("@", 1)[-1] if "@" in proposal.message.from_email else "",
        "action_url": _first_url(action.get("text"), proposal.message.snippet, proposal.analysis.extracted_data.get("summary")),
        "match_candidates": match.ambiguous,
        "can_accept": proposal.application_id is not None or proposal.proposal_type == "create_application",
    }
    return render(
        request,
        "gmail_assistant/proposal_detail.html",
        {
            "proposal": proposal,
            "candidates": candidates,
            "event_tone": _event_tone(proposal.analysis.event_type),
            "review_context": review_context,
        },
    )


@login_required
@require_POST
def accept_gmail_proposal(request, pk: int):
    proposal = get_object_or_404(ApplicationUpdateProposal, pk=pk, user=request.user)
    try:
        result = apply_proposal(
            proposal=proposal,
            user=request.user,
            review_note=request.POST.get("review_note", ""),
        )
    except ProposalApplyError as error:
        logger.info("Gmail Assistant proposal apply rejected user_id=%s error=%s", request.user.id, type(error).__name__)
        messages.error(request, _("The proposal could not be applied."))
    else:
        messages.success(
            request,
            _("Proposal was already accepted.") if result.already_accepted else _("Proposal accepted."),
        )
    return redirect("gmail_assistant:gmail_assistant")


@login_required
@require_POST
def edit_and_accept_gmail_proposal(request, pk: int):
    proposal = get_object_or_404(ApplicationUpdateProposal, pk=pk, user=request.user)
    overrides = {
        "application": {
            field: request.POST[field]
            for field in ("title", "company", "location", "source")
            if request.POST.get(field)
        },
        "interview": {
            field: request.POST[field]
            for field in ("starts_at", "location", "notes")
            if request.POST.get(field)
        },
    }
    try:
        apply_proposal(
            proposal=proposal,
            user=request.user,
            overrides=overrides,
            review_note=request.POST.get("review_note", ""),
        )
    except ProposalApplyError as error:
        logger.info("Gmail Assistant proposal edit rejected user_id=%s error=%s", request.user.id, type(error).__name__)
        messages.error(request, _("The proposal could not be applied."))
    else:
        messages.success(request, _("Proposal accepted with your edits."))
    return redirect("gmail_assistant:gmail_assistant")


@login_required
@require_POST
def assign_gmail_proposal(request, pk: int):
    proposal = get_object_or_404(ApplicationUpdateProposal, pk=pk, user=request.user)
    application = get_object_or_404(JobApplication, pk=request.POST.get("application_id"), user=request.user)
    proposal.application = application
    proposal.match_method = "manual"
    proposal.save(update_fields=["application", "match_method", "updated_at"])
    messages.success(request, _("Application assigned for review."))
    return redirect("gmail_assistant:gmail_proposal_detail", pk=pk)


@login_required
@require_POST
def reject_gmail_proposal(request, pk: int):
    proposal = get_object_or_404(ApplicationUpdateProposal, pk=pk, user=request.user)
    try:
        review_proposal(
            proposal=proposal,
            user=request.user,
            status=ProposalStatus.REJECTED,
            review_note=request.POST.get("review_note", ""),
        )
    except ProposalApplyError as error:
        logger.info("Gmail Assistant proposal rejection failed user_id=%s error=%s", request.user.id, type(error).__name__)
        messages.error(request, _("The proposal could not be reviewed."))
    else:
        messages.success(request, _("Proposal rejected."))
    return redirect("gmail_assistant:gmail_assistant")


@login_required
@require_POST
def ignore_gmail_proposal(request, pk: int):
    proposal = get_object_or_404(ApplicationUpdateProposal, pk=pk, user=request.user)
    try:
        review_proposal(
            proposal=proposal,
            user=request.user,
            status=ProposalStatus.IGNORED,
            review_note=request.POST.get("review_note", ""),
        )
    except ProposalApplyError as error:
        logger.info("Gmail Assistant proposal ignore failed user_id=%s error=%s", request.user.id, type(error).__name__)
        messages.error(request, _("The proposal could not be reviewed."))
    else:
        messages.success(request, _("Proposal ignored."))
    return redirect("gmail_assistant:gmail_assistant")


@login_required
@require_POST
def gmail_assistant_settings(request):
    assistant_settings, _created = GmailAssistantSettings.objects.get_or_create(user=request.user)
    enabled = "ai_enabled" in request.POST
    assistant_settings.ai_enabled = enabled
    if enabled and assistant_settings.ai_consent_at is None:
        assistant_settings.ai_consent_at = timezone.now()
    assistant_settings.save(update_fields=["ai_enabled", "ai_consent_at", "updated_at"])
    messages.success(request, _("AI analysis setting updated."))
    return redirect("gmail_assistant:gmail_assistant")


@login_required
@require_POST
def reset_gmail_assistant(request):
    if not has_dev_tools_access(user=request.user):
        raise Http404
    result = reset_gmail_assistant_data(user=request.user)
    messages.success(
        request,
        _("Dev reset completed: %(messages)d Gmail messages and %(applications)d applications removed.") % result,
    )
    return redirect("gmail_assistant:gmail_assistant")
