from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.applications.models import ApplicationStatus, JobApplication
from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailEventType,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_stats.models import GmailMessage
from apps.interviews.models import InterviewEvent


@pytest.mark.django_db
def test_dashboard_requires_authentication(client):
    response = client.get(reverse("dashboard"))

    assert response.status_code == 302
    assert "/accounts/google/login/" in response.url


@pytest.mark.django_db
def test_dashboard_shows_user_metrics_only(client):
    user = get_user_model().objects.create_user(username="dashboard-user")
    other_user = get_user_model().objects.create_user(username="other-user")
    UserProfile.objects.create(
        user=user,
        google_data_access_consent=True,
        consent_accepted_at=timezone.now(),
    )
    UserProfile.objects.create(
        user=other_user,
        google_data_access_consent=True,
        consent_accepted_at=timezone.now(),
    )
    application = JobApplication.objects.create(
        user=user,
        company="Example GmbH",
        title="Python Developer",
        status=ApplicationStatus.APPLIED,
    )
    JobApplication.objects.create(
        user=other_user,
        company="Hidden GmbH",
        title="Other Role",
        status=ApplicationStatus.APPLIED,
    )
    JobApplication.objects.create(
        user=user,
        company="Rejected GmbH",
        title="Rejected Role",
        status=ApplicationStatus.REJECTED,
    )
    InterviewEvent.objects.create(
        user=user,
        application=application,
        starts_at=timezone.now() + timedelta(days=2),
    )
    client.force_login(user)

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Example GmbH" in content
    assert "Python Developer" in content
    assert "Hidden GmbH" not in content
    assert "dashboard-pill--applied" in content
    assert "dashboard-pill--rejected" in content
    assert f'href="/applications/{application.pk}/"' in content
    assert "js-dashboard-application-row" in content
    assert response.context["active_application_count"] == 1
    assert response.context["follow_up_due_count"] == 0
    assert "Telegram bot" in content
    assert "Gmail" in content
    assert "Drive backups" in content
    assert "Gmail Assistant inactive" in content
    assert response.context["telegram_connected"] is False
    assert response.context["gmail_connected"] is False
    assert response.context["drive_connected"] is False


@pytest.mark.django_db
def test_dashboard_counts_only_unanswered_applications_older_than_fourteen_days(client):
    user = get_user_model().objects.create_user(username="follow-up-dashboard-user")
    JobApplication.objects.create(
        user=user,
        company="Due GmbH",
        title="Python Developer",
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
    response = client.get(reverse("dashboard"))

    assert response.context["follow_up_due_count"] == 1
    assert b"No response for 14+ days" in response.content


@pytest.mark.django_db
def test_dashboard_separates_pending_suggestions_from_accepted_action_history(client):
    user = get_user_model().objects.create_user(username="assistant-dashboard-user")
    application = JobApplication.objects.create(user=user, company="Example GmbH", title="Python Developer")
    message = GmailMessage.objects.create(
        user=user,
        message_id="dashboard-history-message",
        thread_id="dashboard-history-thread",
        received_at=timezone.now(),
        subject="Application update",
    )
    analysis = GmailAnalysis.objects.create(
        user=user, message=message, event_type=GmailEventType.APPLICATION_RECEIVED
    )
    pending = ApplicationUpdateProposal.objects.create(
        user=user, message=message, analysis=analysis, proposal_type=ProposalType.UPDATE_APPLICATION
    )
    accepted_message = GmailMessage.objects.create(
        user=user,
        message_id="dashboard-accepted-message",
        thread_id="dashboard-accepted-thread",
        received_at=timezone.now(),
        subject="Interview confirmed",
    )
    accepted_analysis = GmailAnalysis.objects.create(
        user=user, message=accepted_message, event_type=GmailEventType.INTERVIEW_INVITATION
    )
    accepted = ApplicationUpdateProposal.objects.create(
        user=user,
        message=accepted_message,
        analysis=accepted_analysis,
        application=application,
        proposal_type=ProposalType.CREATE_INTERVIEW,
        status=ProposalStatus.ACCEPTED,
        reviewed_at=timezone.now(),
    )
    client.force_login(user)

    response = client.get(reverse("dashboard"))
    content = response.content.decode()

    assert response.context["pending_proposal_count"] == 1
    assert response.context["accepted_proposal_count"] == 1
    assert list(response.context["pending_proposals"]) == [pending]
    assert list(response.context["accepted_proposals"]) == [accepted]
    assert 'data-dashboard-assistant-tab="new"' in content
    assert 'data-dashboard-assistant-tab="history"' in content
    assert "Application update" in content
    assert "Interview confirmed" in content
