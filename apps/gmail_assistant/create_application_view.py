from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.applications.models import ApplicationSource, ApplicationStatus, JobApplication
from apps.gmail_assistant.models import ApplicationUpdateProposal, ProposalStatus


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

    title = request.POST.get("title", "").strip()[:200]
    company = request.POST.get("company", "").strip()[:200]
    location = request.POST.get("location", "").strip()[:200]
    if not title or not company:
        messages.error(request, _("Job title and company are required."))
        return redirect("gmail_assistant:gmail_proposal_detail", pk=proposal.pk)

    sender = (proposal.message.from_email or "").lower()
    source = ApplicationSource.INDEED if sender.endswith("@indeed.com") else ApplicationSource.OTHER

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
