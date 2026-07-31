from __future__ import annotations

import logging

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_POST

from apps.applications.models import JobApplication
from apps.gmail_assistant.models import ApplicationUpdateProposal, GmailAssistantSettings, ProposalStatus
from apps.gmail_assistant.services.apply_proposal import ProposalApplyError, apply_proposal, review_proposal
from apps.gmail_assistant.services.reset import reset_gmail_assistant_data
from apps.gmail_assistant.services.sync import sync_gmail_messages_for_user
from apps.gmail_stats.services.credentials import get_google_credentials_for_user
from apps.gmail_stats.services.gmail_client import GmailClient

logger = logging.getLogger(__name__)


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
    proposals = proposal_queryset.filter(status=selected_status.value)
    proposal_counts = {
        proposal_status: proposal_queryset.filter(status=proposal_status).count()
        for proposal_status in ProposalStatus.values
    }
    settings, _ = GmailAssistantSettings.objects.get_or_create(user=request.user)
    return render(
        request,
        "gmail_assistant/assistant.html",
        {
            "proposals": proposals[:50],
            "selected_status": selected_status.value,
            "proposal_status_filters": [
                {"value": value, "label": label, "count": proposal_counts[value]}
                for value, label in ProposalStatus.choices
            ],
            "settings": settings,
            "pending_count": proposal_counts[ProposalStatus.PENDING],
            "auto_sync_interval_minutes": django_settings.GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS // 60,
            "dev_tools_enabled": django_settings.GMAIL_ASSISTANT_DEV_TOOLS,
        },
    )


@login_required
def gmail_proposal_detail(request, pk: int):
    proposal = get_object_or_404(
        ApplicationUpdateProposal.objects.select_related("message", "analysis", "application"),
        pk=pk,
        user=request.user,
    )
    candidates = JobApplication.objects.filter(user=request.user).exclude(status__in=["archived", "rejected"])
    return render(request, "gmail_assistant/proposal_detail.html", {"proposal": proposal, "candidates": candidates})


@login_required
@require_POST
def accept_gmail_proposal(request, pk: int):
    proposal = get_object_or_404(ApplicationUpdateProposal, pk=pk, user=request.user)
    try:
        result = apply_proposal(proposal=proposal, user=request.user)
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
            for field in ("title", "company", "location")
            if request.POST.get(field)
        },
        "interview": {
            field: request.POST[field]
            for field in ("starts_at", "location", "notes")
            if request.POST.get(field)
        },
    }
    try:
        apply_proposal(proposal=proposal, user=request.user, overrides=overrides)
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
        review_proposal(proposal=proposal, user=request.user, status=ProposalStatus.REJECTED)
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
        review_proposal(proposal=proposal, user=request.user, status=ProposalStatus.IGNORED)
    except ProposalApplyError as error:
        logger.info("Gmail Assistant proposal ignore failed user_id=%s error=%s", request.user.id, type(error).__name__)
        messages.error(request, _("The proposal could not be reviewed."))
    else:
        messages.success(request, _("Proposal ignored."))
    return redirect("gmail_assistant:gmail_assistant")


@login_required
@require_POST
def gmail_assistant_settings(request):
    settings, _ = GmailAssistantSettings.objects.get_or_create(user=request.user)
    enabled = "ai_enabled" in request.POST
    was_enabled = settings.ai_enabled
    settings.ai_enabled = enabled
    if enabled and settings.ai_consent_at is None:
        settings.ai_consent_at = timezone.now()
    settings.save(update_fields=["ai_enabled", "ai_consent_at", "updated_at"])

    if enabled and not was_enabled:
        try:
            credentials = get_google_credentials_for_user(request.user)
        except (RuntimeError, ValueError) as error:
            logger.warning("Gmail Assistant credential lookup failed user_id=%s error=%s", request.user.id, type(error).__name__)
            credentials = None
        if not credentials:
            messages.warning(
                request,
                _("AI analysis enabled, but Gmail is not connected. Reconnect Google and then sync Gmail."),
            )
        else:
            try:
                result = sync_gmail_messages_for_user(
                    user=request.user,
                    gmail_client=GmailClient(credentials),
                    days=180,
                    max_results_each=500,
                    reanalyze_existing=True,
                )
            except (RuntimeError, ValueError) as error:
                logger.warning("Initial Gmail Assistant sync failed user_id=%s error=%s", request.user.id, type(error).__name__)
                messages.warning(request, _("AI analysis is enabled, but Gmail sync failed. Try again later."))
            else:
                messages.success(
                    request,
                    ngettext(
                        "AI analysis enabled. Gmail synced; %(count)d suggestion created.",
                        "AI analysis enabled. Gmail synced; %(count)d suggestions created.",
                        result["proposals_created"],
                    )
                    % {"count": result["proposals_created"]},
                )
    else:
        messages.success(request, _("AI analysis setting updated."))
    return redirect("gmail_assistant:gmail_assistant")


@login_required
@require_POST
def reset_gmail_assistant(request):
    if not django_settings.GMAIL_ASSISTANT_DEV_TOOLS:
        raise Http404
    result = reset_gmail_assistant_data(user=request.user)
    messages.success(
        request,
        _("Dev reset completed: %(messages)d Gmail messages and %(applications)d applications removed.") % result,
    )
    return redirect("gmail_assistant:gmail_assistant")
