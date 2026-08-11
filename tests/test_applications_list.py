from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.applications.models import ApplicationStatus, JobApplication
from apps.gmail_assistant.models import (
    AnalysisClassifier,
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailEventType,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_stats.models import GmailMessage


@pytest.mark.django_db
def test_application_list_highlights_rows_by_current_status(client, django_user_model):
    user = django_user_model.objects.create_user("applications-user", email="applications@example.com")
    JobApplication.objects.create(
        user=user,
        company="Example GmbH",
        title="Developer",
        status=ApplicationStatus.REJECTED,
    )
    client.force_login(user)

    response = client.get(reverse("applications:list"))

    assert response.status_code == 200
    assert b"apps-table__row--rejected" in response.content
    assert b"application-card--rejected" in response.content


@pytest.mark.django_db
def test_application_list_filters_by_accepted_ai_processing(client, django_user_model):
    user = django_user_model.objects.create_user("applications-user", email="applications@example.com")
    ai_application = JobApplication.objects.create(user=user, company="AI GmbH", title="AI Developer")
    manual_application = JobApplication.objects.create(user=user, company="Manual GmbH", title="Manual Developer")
    message = GmailMessage.objects.create(
        user=user,
        message_id="applications-ai-filter",
        thread_id="applications-ai-filter-thread",
        received_at=timezone.now(),
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        classifier=AnalysisClassifier.AI,
        event_type=GmailEventType.APPLICATION_RECEIVED,
    )
    ApplicationUpdateProposal.objects.create(
        user=user,
        message=message,
        analysis=analysis,
        application=ai_application,
        proposal_type=ProposalType.UPDATE_APPLICATION,
        status=ProposalStatus.ACCEPTED,
    )
    client.force_login(user)

    processed = client.get(reverse("applications:list"), {"ai": "processed"})
    without_ai = client.get(reverse("applications:list"), {"ai": "without"})

    assert list(processed.context["items"]) == [ai_application]
    assert list(without_ai.context["items"]) == [manual_application]
    assert b'name="ai"' in processed.content
