from __future__ import annotations

import logging
import re
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Max, Q
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
    ProposalType,
)
from apps.gmail_assistant.services.ai_policy import AIUsagePolicy
from apps.gmail_assistant.services.application_matcher import match_for_message
from apps.gmail_assistant.services.apply_proposal import ProposalApplyError, apply_proposal, review_proposal
from apps.gmail_assistant.services.bulk_create import (
    BULK_CREATE_MIN_CONFIDENCE,
    bulk_create_eligible_proposals,
    eligible_bulk_create_proposals,
)
from apps.gmail_assistant.services.dev_tools import has_dev_tools_access
from apps.gmail_assistant.services.reset import reset_gmail_assistant_data

logger = logging.getLogger(__name__)


def _auto_sync_interval_display(seconds: int) -> str:
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
    return f"{seconds} seconds"


def _event_tone(event_type: str) -> str:
    if event_type == GmailEventType.REJECTION:
        return "danger"
    if event_type in {GmailEventType.INTERVIEW_INVITATION, GmailEventType.INTERVIEW_RESCHEDULED}:
        return "success"
    if event_type == GmailEventType.OFFER:
        return "warning"
    if event_type in {
        GmailEventType.APPLICATION_CONFIRMATION_REQUIRED,
        GmailEventType.APPLICATION_DRAFT_REMINDER,
        GmailEventType.APPLICATION_SENT,
        GmailEventType.APPLICATION_RECEIVED,
    }:
        return "primary"
    return "secondary"


def _proposal_event_label(proposal: ApplicationUpdateProposal) -> str:
    if proposal.analysis.extracted_data.get("sent_kind") == "direct_application":
        return "myself_sent"
    return proposal.analysis.get_event_type_display()


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


def _paginated_proposal_groups(
    *,
    proposal_queryset,
    status: str,
    page_number: str | None,
    search_query: str = "",
    per_page: int = 10,
):
    filtered = proposal_queryset.filter(status=status)
    if search_query:
        filtered = filtered.filter(
            Q(message__subject__icontains=search_query)
            | Q(message__from_email__icontains=search_query)
            | Q(application__company__icontains=search_query)
            | Q(application__title__icontains=search_query)
        )

    grouped_messages = (
        filtered.order_by()
        .values("message_id")
        .annotate(message_received_at=Max("message__received_at"), latest_created_at=Max("created_at"))
        .order_by("-message_received_at", "-latest_created_at")
    )
    paginator = Paginator(grouped_messages, per_page)
    page_obj = paginator.get_page(page_number)
    message_ids = [row["message_id"] for row in page_obj.object_list]
    proposals = filtered.filter(message_id__in=message_ids)
    groups_by_message_id = {
        group["message"].id: group for group in _group_proposals_by_message(proposals)
    }
    groups = [groups_by_message_id[message_id] for message_id in message_ids]
    return groups, page_obj, paginator


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

    history_search = ""
    per_page = 10
    if selected_status == ProposalStatus.ACCEPTED:
        history_search = (request.GET.get("q") or "").strip()
        per_page = 20

    proposal_groups, page_obj, paginator = _paginated_proposal_groups(
        proposal_queryset=proposal_queryset,
        status=selected_status.value,
        page_number=request.GET.get("page"),
        search_query=history_search,
        per_page=per_page,
    )
    proposal_counts = {
        proposal_status: proposal_queryset.filter(status=proposal_status).count()
        for proposal_status in ProposalStatus.values
    }
    assistant_settings, _created = GmailAssistantSettings.objects.get_or_create(user=request.user)
    ai_policy = AIUsagePolicy.from_environment()
    ai_daily_used = ai_policy.daily_usage(user=request.user)
    ai_daily_remaining = max(0, ai_policy.daily_limit - ai_daily_used)
    bulk_create_candidate_count = len(eligible_bulk_create_proposals(user=request.user))
    unlinked_pending_count = proposal_queryset.filter(
        status=ProposalStatus.PENDING,
        application__isnull=True,
    ).count()
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
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "gmail_assistant/assistant_history_search.html",
        {
            "proposal_groups": proposal_groups,
            "page_obj": page_obj,
            "paginator": paginator,
            "base_qs": params.urlencode(),
            "selected_status": selected_status.value,
            "history_search": history_search,
            "proposal_status_filters": [
                {"value": value, "label": label, "count": proposal_counts[value]}
                for value, label in ProposalStatus.choices
            ],
            "secondary_proposal_status_filters": [
                {"value": value, "label": label, "count": proposal_counts[value]}
                for value, label in ProposalStatus.choices
                if value in {ProposalStatus.REJECTED, ProposalStatus.IGNORED}
            ],
            "settings": assistant_settings,
            "pending_count": proposal_counts[ProposalStatus.PENDING],
            "accepted_count": proposal_counts[ProposalStatus.ACCEPTED],
            "technical_event_types": {
                GmailEventType.APPLICATION_CONFIRMATION_REQUIRED,
                GmailEventType.APPLICATION_SENT,
                GmailEventType.APPLICATION_RECEIVED,
            },
            "interview_event_types": {
                GmailEventType.INTERVIEW_INVITATION,
                GmailEventType.INTERVIEW_RESCHEDULED,
            },
            "auto_sync_interval_display": _auto_sync_interval_display(
                django_settings.GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS
            ),
            "next_automatic_check_at": next_automatic_check_at,
            "dev_tools_enabled": has_dev_tools_access(user=request.user),
            "ai_model_name": django_settings.OPENAI_EMAIL_MODEL,
            "ai_daily_limit": ai_policy.daily_limit,
            "ai_daily_used": ai_daily_used,
            "ai_daily_remaining": ai_daily_remaining,
            "ai_confidence_threshold": django_settings.GMAIL_ASSISTANT_AI_CONFIDENCE_THRESHOLD,
            "bulk_create_candidate_count": bulk_create_candidate_count,
            "bulk_create_min_confidence": BULK_CREATE_MIN_CONFIDENCE,
            "unlinked_pending_count": unlinked_pending_count,
        },
    )


@login_required
def gmail_proposal_detail(request, pk: int):
    proposal = get_object_or_404(
        ApplicationUpdateProposal.objects.select_related("message", "analysis", "application"),
        pk=pk,
        user=request.user,
    )
    match = match_for_message(
        user=request.user,
        message=proposal.message,
        extracted_data=proposal.analysis.extracted_data,
        event_type=proposal.analysis.event_type,
    )
    if proposal.proposal_type == ProposalType.CREATE_APPLICATION:
        # A new application must not offer unrelated records for linking. Only
        # matching candidates are relevant here, and a lack of them is expected.
        candidates = [candidate.application for candidate in match.ambiguous if candidate.application is not None]
    else:
        candidates = list(
            JobApplication.objects.filter(user=request.user)
            .exclude(status__in=["archived", "rejected"])
            .order_by("-updated_at", "-pk")
        )
    action = proposal.changes.get("action") if isinstance(proposal.changes.get("action"), dict) else {}
    pending_create_proposal = None
    pending_create_id = proposal.changes.get("pending_create_proposal_id")
    if isinstance(pending_create_id, int):
        pending_create_proposal = ApplicationUpdateProposal.objects.filter(
            pk=pending_create_id,
            user=request.user,
            proposal_type=ProposalType.CREATE_APPLICATION,
            status=ProposalStatus.PENDING,
        ).first()
    review_context = {
        "sender_domain": proposal.message.from_email.rsplit("@", 1)[-1] if "@" in proposal.message.from_email else "",
        "action_url": _first_url(action.get("text"), proposal.message.snippet, proposal.analysis.extracted_data.get("summary")),
        "match_candidates": tuple(candidate for candidate in match.ambiguous if candidate.application is not None),
        "pending_create_proposal": pending_create_proposal,
        "can_accept": (
            proposal.application_id is not None
            or proposal.proposal_type == "create_application"
            or (
                proposal.proposal_type == ProposalType.ACTION_REQUIRED
                and proposal.analysis.event_type == GmailEventType.APPLICATION_DRAFT_REMINDER
            )
        ) and pending_create_proposal is None,
        "is_draft_reminder": proposal.analysis.event_type == GmailEventType.APPLICATION_DRAFT_REMINDER,
    }
    return render(
        request,
        "gmail_assistant/proposal_detail.html",
        {
            "proposal": proposal,
            "candidates": candidates,
            "event_tone": _event_tone(proposal.analysis.event_type),
            "event_label": _proposal_event_label(proposal),
            "review_context": review_context,
        },
    )


@login_required
@require_POST
def bulk_create_gmail_applications(request):
    result = bulk_create_eligible_proposals(user=request.user)
    if result.created:
        messages.success(
            request,
            _("Created %(created)d applications from high-confidence AI suggestions.") % {"created": result.created},
        )
    if result.skipped_as_possible_duplicate:
        messages.warning(
            request,
            _("%(count)d possible duplicates were left pending for review.")
            % {"count": result.skipped_as_possible_duplicate},
        )
    if result.failed:
        messages.warning(
            request,
            _("%(count)d suggestions could not be created and remain pending.") % {"count": result.failed},
        )
    if result.linked_for_review:
        messages.info(
            request,
            _("%(count)d remaining suggestions were linked to exact application matches for review.")
            % {"count": result.linked_for_review},
        )
    if not any((result.created, result.skipped_as_possible_duplicate, result.failed, result.linked_for_review)):
        messages.info(request, _("There are no eligible AI suggestions to create."))
    return redirect("gmail_assistant:gmail_assistant")


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
    auto_apply_enabled = enabled and "auto_apply_enabled" in request.POST
    assistant_settings.ai_enabled = enabled
    assistant_settings.auto_apply_enabled = auto_apply_enabled
    if enabled and assistant_settings.ai_consent_at is None:
        assistant_settings.ai_consent_at = timezone.now()
    if auto_apply_enabled and assistant_settings.auto_apply_consent_at is None:
        assistant_settings.auto_apply_consent_at = timezone.now()
    assistant_settings.save(
        update_fields=[
            "ai_enabled",
            "ai_consent_at",
            "auto_apply_enabled",
            "auto_apply_consent_at",
            "updated_at",
        ]
    )
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


@login_required
@require_POST
def reset_ai_daily_limit(request):
    if not has_dev_tools_access(user=request.user):
        raise Http404
    assistant_settings, _created = GmailAssistantSettings.objects.get_or_create(user=request.user)
    assistant_settings.ai_daily_usage_reset_at = timezone.now()
    assistant_settings.ai_daily_usage_date = timezone.localdate()
    assistant_settings.ai_daily_usage_count = 0
    assistant_settings.save(
        update_fields=[
            "ai_daily_usage_reset_at",
            "ai_daily_usage_date",
            "ai_daily_usage_count",
            "updated_at",
        ]
    )
    messages.success(request, _("Today's AI limit was reset for this user."))
    return redirect("gmail_assistant:gmail_assistant")
