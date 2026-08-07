from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.applications.models import ApplicationSource, ApplicationStatus, JobApplication
from apps.gmail_assistant.models import ApplicationUpdateProposal, GmailEventType, ProposalStatus


def _application_source(sender: str) -> str:
    return ApplicationSource.INDEED if sender.endswith("@indeed.com") else ApplicationSource.OTHER


def _application_values(request):
    return (
        request.POST.get("title", "").strip()[:200],
        request.POST.get("company", "").strip()[:200],
        request.POST.get("location", "").strip()[:200],
    )


@login_required
@require_POST
def create_application_for_proposal(request, pk: int):
    """Create and link an application without accepting the Gmail proposal."""
    proposal = get_object_or_404(
        ApplicationUpdateProposal.objects.select_related("message", "analysis"),
        pk=pk,
        user=request.user,
        status=ProposalStatus.PENDING,
    )

    title, company, location = _application_values(request)
    if not title or not company:
        messages.error(request, _("Job title and company are required."))
        return redirect("gmail_assistant:gmail_proposal_detail", pk=proposal.pk)

    source = _application_source((proposal.message.from_email or "").lower())

    with transaction.atomic():
        application = JobApplication.objects.create(
            user=request.user,
            title=title,
            company=company,
            location=location,
            source=source,
            status=ApplicationStatus.APPLIED,
            applied_at=proposal.message.received_at,
            notes=_("Created from Gmail Assistant proposal."),
        )
        proposal.application = application
        proposal.match_method = "manual_created"
        proposal.match_score = 100
        proposal.save(update_fields=["application", "match_method", "match_score", "updated_at"])

        proposal.message.application = application
        proposal.message.is_user_verified = True
        proposal.message.save(update_fields=["application", "is_user_verified", "updated_at"])

    messages.success(request, _("Application created and linked. Review the proposal before accepting it."))
    return redirect("gmail_assistant:gmail_proposal_detail", pk=proposal.pk)


@login_required
@require_POST
def create_rejected_application_for_proposal(request, pk: int):
    """Manually record an otherwise unmatchable rejection as a rejected application."""
    proposal = get_object_or_404(
        ApplicationUpdateProposal.objects.select_related("message", "analysis"),
        pk=pk,
        user=request.user,
        status=ProposalStatus.PENDING,
        application__isnull=True,
        analysis__event_type=GmailEventType.REJECTION,
    )

    title, company, location = _application_values(request)
    if not title or not company:
        messages.error(request, _("Job title and company are required."))
        return redirect("gmail_assistant:gmail_proposal_detail", pk=proposal.pk)

    with transaction.atomic():
        application = JobApplication.objects.create(
            user=request.user,
            title=title,
            company=company,
            location=location,
            source=_application_source((proposal.message.from_email or "").lower()),
            status=ApplicationStatus.REJECTED,
            # This is the only known timestamp. The note makes clear that it is
            # the rejection email date, not a fabricated application confirmation.
            applied_at=proposal.message.received_at,
            recruiter_reply_at=proposal.message.received_at,
            notes=_("Created from an immediate rejection email. The original application date is unknown."),
        )
        proposal.application = application
        proposal.match_method = "manual_created_immediate_rejection"
        proposal.match_score = 100
        proposal.status = ProposalStatus.ACCEPTED
        proposal.reviewed_at = timezone.now()
        proposal.review_note = _("Created as a rejected application after manual review.")
        proposal.save(
            update_fields=[
                "application",
                "match_method",
                "match_score",
                "status",
                "reviewed_at",
                "review_note",
                "updated_at",
            ]
        )
        proposal.message.application = application
        proposal.message.is_user_verified = True
        proposal.message.save(update_fields=["application", "is_user_verified", "updated_at"])

    messages.success(request, _("Rejected application created and Gmail rejection recorded."))
    return redirect("gmail_assistant:gmail_assistant")
