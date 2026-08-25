from __future__ import annotations

import pytest
from django.utils import timezone

from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailEventType,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_assistant.services.application_matcher import ApplicationMatch
from apps.gmail_assistant.services.proposal_builder import build_proposals
from apps.gmail_stats.models import GmailMessage


@pytest.mark.django_db
@pytest.mark.parametrize(
    "reviewed_status",
    [ProposalStatus.ACCEPTED, ProposalStatus.REJECTED, ProposalStatus.IGNORED],
)
def test_reviewed_create_proposal_does_not_return_to_pending(django_user_model, reviewed_status):
    user = django_user_model.objects.create_user("proposal-idempotency", email="proposal-idempotency@example.com")
    message = GmailMessage.objects.create(
        user=user,
        message_id=f"reviewed-create-{reviewed_status}",
        thread_id=f"reviewed-thread-{reviewed_status}",
        received_at=timezone.now(),
        subject="Application received",
        from_email="jobs@example.com",
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        event_type=GmailEventType.APPLICATION_RECEIVED,
        is_job_related=True,
        confidence=90,
        extracted_data={"company": "Example GmbH", "position_title": "Python Developer"},
    )
    unmatched = ApplicationMatch(suggested=None, ambiguous=())

    original = build_proposals(message=message, analysis=analysis, match=unmatched)[0]
    original.status = reviewed_status
    original.reviewed_at = timezone.now()
    original.save(update_fields=["status", "reviewed_at", "updated_at"])

    recreated = build_proposals(message=message, analysis=analysis, match=unmatched)

    assert recreated == []
    assert ApplicationUpdateProposal.objects.filter(
        message=message,
        analysis=analysis,
        proposal_type=ProposalType.CREATE_APPLICATION,
        status=ProposalStatus.PENDING,
    ).count() == 0
    assert ApplicationUpdateProposal.objects.filter(
        message=message,
        analysis=analysis,
        proposal_type=ProposalType.CREATE_APPLICATION,
        status=reviewed_status,
    ).count() == 1
