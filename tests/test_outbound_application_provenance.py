from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.applications.models import JobApplication
from apps.gmail_assistant.models import (
    AnalysisClassifier,
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailEventType,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_stats.models import GmailDirection, GmailMessage


@pytest.fixture
def sent_application(db, django_user_model):
    user = django_user_model.objects.create_user("sent-application-user", email="sender@example.com")
    sent_at = timezone.now() - timedelta(days=2)
    application = JobApplication.objects.create(
        user=user,
        company="Klengel",
        title="im Bereich Softwareentwicklung",
        applied_at=sent_at,
    )
    message = GmailMessage.objects.create(
        user=user,
        message_id="sent-application-message",
        thread_id="sent-application-thread",
        direction=GmailDirection.OUTBOUND,
        received_at=sent_at,
        subject="Bewerbung im Bereich Softwareentwicklung",
        application=application,
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        classifier=AnalysisClassifier.AI,
        event_type=GmailEventType.APPLICATION_SENT,
        is_job_related=True,
        confidence=95,
        extracted_data={"sent_kind": "direct_application"},
    )
    ApplicationUpdateProposal.objects.create(
        user=user,
        message=message,
        analysis=analysis,
        application=application,
        proposal_type=ProposalType.CREATE_APPLICATION,
        status=ProposalStatus.ACCEPTED,
    )
    JobApplication.objects.filter(pk=application.pk).update(updated_at=sent_at + timedelta(days=2))
    application.refresh_from_db()
    return user, application, sent_at


@pytest.mark.django_db
def test_application_list_marks_application_as_sent_by_user(client, sent_application):
    user, application, _ = sent_application
    client.force_login(user)

    response = client.get(reverse("applications:list"))

    assert response.status_code == 200
    item = next(item for item in response.context["items"] if item.pk == application.pk)
    assert item.has_ai_processed_proposal is True
    assert item.has_sent_by_user_proposal is True
    assert b"Sent by me" in response.content


@pytest.mark.django_db
def test_application_detail_uses_business_activity_and_hides_missing_hr_reply(client, sent_application):
    user, application, sent_at = sent_application
    client.force_login(user)

    response = client.get(reverse("applications:detail", args=[application.pk]))

    assert response.status_code == 200
    assert response.context["sent_by_user"] is True
    assert response.context["last_activity_at"] == sent_at
    assert b"Sent by me" in response.content
    assert b"HR reply" not in response.content
