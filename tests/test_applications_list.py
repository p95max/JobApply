from __future__ import annotations

from datetime import timedelta

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


@pytest.mark.django_db
def test_application_list_filters_to_unanswered_applications_older_than_fourteen_days(client, django_user_model):
    user = django_user_model.objects.create_user("applications-user", email="applications@example.com")
    due = JobApplication.objects.create(
        user=user,
        company="Due GmbH",
        title="Follow-up Developer",
        status=ApplicationStatus.APPLIED,
        applied_at=timezone.now() - timedelta(days=15),
    )
    JobApplication.objects.create(
        user=user,
        company="Fresh GmbH",
        title="Fresh Developer",
        status=ApplicationStatus.APPLIED,
        applied_at=timezone.now() - timedelta(days=13),
    )
    JobApplication.objects.create(
        user=user,
        company="Answered GmbH",
        title="Answered Developer",
        status=ApplicationStatus.APPLIED,
        applied_at=timezone.now() - timedelta(days=20),
        recruiter_reply_at=timezone.now(),
    )
    client.force_login(user)

    response = client.get(reverse("applications:list"), {"follow_up": "1"})

    assert list(response.context["items"]) == [due]
    assert response.context["follow_up"] is True
    assert b'name="follow_up"' in response.content
