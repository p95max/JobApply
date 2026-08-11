from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.applications.models import ApplicationSource, ApplicationStatus, JobApplication
from apps.applications.services.limits import ApplicationLimitError, ensure_application_capacity
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

    try:
        with transaction.atomic():
            ensure_application_capacity(user=request.user)
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
    except ApplicationLimitError as error:
        messages.error(request, str(error))
        return redirect("gmail_assistant:gmail_proposal_detail", pk=proposal.pk)

    messages.success(request, _("Application created and linked. Review the proposal before accepting it."))
    return redirect("gmail_assistant:gmail_proposal_detail", pk=proposal.pk)


@login_required
@require_POST
def create_rejected_application_for_proposal(request, pk: int):
    """Refuse unsafe creation from a rejection with no matched application.

    A rejection timestamp is not an application date. Keeping this endpoint
    inert also protects old bookmarked form actions while directing the user
    to link a real application first.
    """
    proposal = get_object_or_404(
        ApplicationUpdateProposal.objects.select_related("message", "analysis"),
        pk=pk,
        user=request.user,
        status=ProposalStatus.PENDING,
        application__isnull=True,
        analysis__event_type=GmailEventType.REJECTION,
    )

    messages.error(
        request,
        _(
            "An unmatched rejection cannot create a new application. "
            "Link the original application first, or ignore this suggestion."
        ),
    )
    return redirect("gmail_assistant:gmail_proposal_detail", pk=proposal.pk)
