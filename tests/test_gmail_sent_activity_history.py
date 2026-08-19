from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

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
def test_proposal_less_direct_sent_application_is_added_to_action_history(client):
    user = get_user_model().objects.create_user(username="sent-history", password="test-pass")
    message = GmailMessage.objects.create(
        user=user,
        message_id="gmail-sent-klengel",
        thread_id="thread-klengel",
        direction=GmailDirection.OUTBOUND,
        received_at=timezone.now(),
        from_email="owner@example.com",
        to_emails=["info@klengel.de"],
        subject="Bewerbung im Bereich Softwareentwicklung",
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
            "position_title": "Softwareentwicklung",
        },
    )
    settings = GmailAssistantSettings.objects.create(user=user, ai_enabled=True)

    settings.last_successful_run_at = timezone.now()
    settings.save(update_fields=["last_successful_run_at", "updated_at"])

    activity = ApplicationUpdateProposal.objects.get(
        user=user,
        message=message,
        analysis=analysis,
        proposal_type=ProposalType.ACTIVITY,
    )
    assert activity.status == ProposalStatus.ACCEPTED
    assert activity.changes == {"activity": {"kind": "application_sent", "source": "gmail_sent"}}

    client.force_login(user)
    response = client.get(reverse("gmail_assistant:gmail_assistant"), {"status": ProposalStatus.ACCEPTED})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Bewerbung im Bereich Softwareentwicklung" in content
    assert "Gmail activity" in content


@pytest.mark.django_db
def test_direct_sent_activity_does_not_duplicate_an_existing_proposal():
    user = get_user_model().objects.create_user(username="sent-existing", password="test-pass")
    message = GmailMessage.objects.create(
        user=user,
        message_id="gmail-sent-existing",
        thread_id="thread-existing",
        direction=GmailDirection.OUTBOUND,
        received_at=timezone.now(),
        from_email="owner@example.com",
        to_emails=["jobs@example.com"],
        subject="Bewerbung als Python Developer",
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        event_type=GmailEventType.APPLICATION_SENT,
        is_job_related=True,
        confidence=95,
        extracted_data={
            "sent_kind": "direct_application",
            "company": "Example",
            "position_title": "Python Developer",
        },
    )
    ApplicationUpdateProposal.objects.create(
        user=user,
        message=message,
        analysis=analysis,
        proposal_type=ProposalType.CREATE_APPLICATION,
        status=ProposalStatus.PENDING,
        changes={"application": {"company": "Example", "title": "Python Developer"}},
    )
    settings = GmailAssistantSettings.objects.create(user=user, ai_enabled=True)

    settings.last_successful_run_at = timezone.now()
    settings.save(update_fields=["last_successful_run_at", "updated_at"])

    assert not ApplicationUpdateProposal.objects.filter(
        user=user,
        message=message,
        analysis=analysis,
        proposal_type=ProposalType.ACTIVITY,
    ).exists()
