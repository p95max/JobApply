from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.applications.models import JobApplication
from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailAssistantSettings,
    GmailEventType,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_stats.models import GmailDirection, GmailMessage


@pytest.mark.django_db
def test_canonical_sent_history_restores_create_application_semantics():
    user = get_user_model().objects.create_user(username="sent-create-history", password="test-pass")
    application = JobApplication.objects.create(
        user=user,
        title="im Bereich Softwareentwicklung",
        company="Klengel",
        status="applied",
    )
    message = GmailMessage.objects.create(
        user=user,
        message_id="gmail-sent-create-history",
        thread_id="thread-sent-create-history",
        direction=GmailDirection.OUTBOUND,
        received_at=timezone.now(),
        from_email="owner@example.com",
        to_emails=["info@klengel.de"],
        subject="Bewerbung im Bereich Softwareentwicklung",
        application=application,
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        event_type=GmailEventType.APPLICATION_SENT,
        is_job_related=True,
        confidence=95,
        extracted_data={
            "sent_kind": "direct_application",
            "company": "Klengel",
            "position_title": "im Bereich Softwareentwicklung",
        },
    )
    proposal = ApplicationUpdateProposal.objects.create(
        user=user,
        message=message,
        analysis=analysis,
        application=application,
        proposal_type=ProposalType.ACTIVITY,
        status=ProposalStatus.ACCEPTED,
        match_score=100,
        match_method="recreated_after_application_deletion",
        changes={
            "application": {
                "operation": "create",
                "title": "im Bereich Softwareentwicklung",
                "company": "Klengel",
                "status": "applied",
                "applied_at": message.received_at.isoformat(),
            },
            "activity": {"kind": "application_sent", "source": "gmail_sent"},
        },
        reviewed_at=timezone.now(),
    )
    settings = GmailAssistantSettings.objects.create(user=user, ai_enabled=True)

    settings.last_successful_run_at = timezone.now()
    settings.save(update_fields=["last_successful_run_at", "updated_at"])

    proposal.refresh_from_db()
    assert proposal.proposal_type == ProposalType.CREATE_APPLICATION
    assert proposal.status == ProposalStatus.ACCEPTED
    assert proposal.application_id == application.pk
    assert proposal.changes["activity"] == {"kind": "application_sent", "source": "gmail_sent"}
