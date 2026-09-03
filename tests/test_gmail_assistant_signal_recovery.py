from __future__ import annotations

from datetime import timedelta

import pytest
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
def test_sent_recovery_relinks_existing_application_and_retires_duplicate_pending(django_user_model):
    user = django_user_model.objects.create_user("owner", email="owner@example.com")
    sent_at = timezone.now()

    message = GmailMessage.objects.create(
        user=user,
        message_id="sent-application-1",
        thread_id="thread-application-1",
        direction=GmailDirection.OUTBOUND,
        received_at=sent_at,
        from_email="owner@example.com",
        subject=(
            "Bewerbung um eine Ausbildung zum Fachinformatiker für Anwendungsentwicklung "
            "– Kennziffer Azubi-FI-2027"
        ),
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        event_type=GmailEventType.APPLICATION_SENT,
        is_job_related=True,
        confidence=68,
        extracted_data={
            "sent_kind": "direct_application",
            "company": "Landesdirektion Sachsen",
            "position_title": "Ausbildung zum Fachinformatiker für Anwendungsentwicklung",
        },
    )

    stale_changes = {
        "application": {
            "operation": "create",
            "title": "Ausbildung zum Fachinformatiker für Anwendungsentwicklung – Kennziffer Azubi-FI-2027",
            "company": "Landesdirektion Sachsen",
            "location": "",
            "source": "other",
            "status": "applied",
            "applied_at": sent_at.isoformat(),
        }
    }
    stale_accepted = ApplicationUpdateProposal.objects.create(
        user=user,
        message=message,
        analysis=analysis,
        application=None,
        proposal_type=ProposalType.CREATE_APPLICATION,
        status=ProposalStatus.ACCEPTED,
        match_score=100,
        match_method="exact_company_title",
        changes=stale_changes,
        reviewed_at=sent_at,
    )
    duplicate_pending = ApplicationUpdateProposal.objects.create(
        user=user,
        message=message,
        analysis=analysis,
        application=None,
        proposal_type=ProposalType.CREATE_APPLICATION,
        status=ProposalStatus.PENDING,
        match_score=0,
        match_method="recreated_after_application_deletion",
        changes=stale_changes,
    )

    application = JobApplication.objects.create(
        user=user,
        company="Freistaat Sachsen / Landesdirektion Sachsen",
        title="Ausbildung zum Fachinformatiker für Anwendungsentwicklung",
        status="applied",
        source="other",
        applied_at=sent_at - timedelta(hours=2),
    )

    settings = GmailAssistantSettings.objects.create(user=user)
    settings.last_successful_run_at = timezone.now()
    settings.save(update_fields=["last_successful_run_at", "updated_at"])

    stale_accepted.refresh_from_db()
    duplicate_pending.refresh_from_db()
    message.refresh_from_db()

    assert stale_accepted.application_id == application.pk
    assert message.application_id == application.pk
    assert duplicate_pending.status == ProposalStatus.IGNORED
    assert duplicate_pending.reviewed_at is not None
    assert not ApplicationUpdateProposal.objects.filter(
        user=user,
        message=message,
        analysis=analysis,
        proposal_type=ProposalType.CREATE_APPLICATION,
        status=ProposalStatus.PENDING,
    ).exists()
