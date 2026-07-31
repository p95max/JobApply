from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.applications.models import JobApplication
from apps.gmail_stats.models import (
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailAssistantSettings,
    GmailEventType,
    GmailMessage,
    ProposalStatus,
    ProposalType,
)


@pytest.fixture
def proposal(db, django_user_model):
    user = django_user_model.objects.create_user("owner", email="owner@example.com")
    UserProfile.objects.create(user=user, google_data_access_consent=True)
    application = JobApplication.objects.create(user=user, company="Example GmbH", title="Developer")
    message = GmailMessage.objects.create(
        user=user,
        message_id="message-1",
        thread_id="thread-1",
        received_at=timezone.now() + timedelta(hours=1),
        subject="Application update",
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        event_type=GmailEventType.GENERAL_UPDATE,
        is_job_related=True,
    )
    return ApplicationUpdateProposal.objects.create(
        user=user,
        message=message,
        analysis=analysis,
        application=application,
        proposal_type=ProposalType.UPDATE_APPLICATION,
        changes={"application": {"status": {"old": "applied", "new": "replied"}}},
    )


@pytest.mark.django_db
def test_assistant_requires_authentication(client):
    response = client.get(reverse("gmail_stats:gmail_assistant"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_write_endpoints_reject_get_requests(client, proposal):
    client.force_login(proposal.user)
    urls = [
        reverse("gmail_stats:accept_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_stats:edit_accept_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_stats:assign_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_stats:reject_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_stats:ignore_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_stats:gmail_assistant_settings"),
    ]

    assert all(client.get(url).status_code == 405 for url in urls)


@pytest.mark.django_db
def test_user_cannot_review_another_users_proposal(client, proposal, django_user_model):
    other = django_user_model.objects.create_user("other", email="other@example.com")
    UserProfile.objects.create(user=other, google_data_access_consent=True)
    client.force_login(other)

    response = client.post(reverse("gmail_stats:accept_gmail_proposal", args=[proposal.pk]))

    assert response.status_code == 404
    proposal.refresh_from_db()
    assert proposal.status == ProposalStatus.PENDING


@pytest.mark.django_db
def test_accept_endpoint_applies_a_pending_proposal(client, proposal):
    client.force_login(proposal.user)

    response = client.post(reverse("gmail_stats:accept_gmail_proposal", args=[proposal.pk]))

    assert response.status_code == 302
    proposal.refresh_from_db()
    proposal.application.refresh_from_db()
    assert proposal.status == ProposalStatus.ACCEPTED
    assert proposal.application.status == "replied"


@pytest.mark.django_db
def test_assign_endpoint_accepts_only_current_users_application(client, proposal, django_user_model):
    other = django_user_model.objects.create_user("other", email="other@example.com")
    other_application = JobApplication.objects.create(user=other, company="Other", title="Role")
    client.force_login(proposal.user)

    response = client.post(
        reverse("gmail_stats:assign_gmail_proposal", args=[proposal.pk]),
        {"application_id": other_application.pk},
    )

    assert response.status_code == 404
    proposal.refresh_from_db()
    assert proposal.match_method == ""


@pytest.mark.django_db
def test_enabling_ai_analysis_starts_gmail_sync(client, proposal, monkeypatch):
    client.force_login(proposal.user)
    credentials = object()
    monkeypatch.setattr("apps.gmail_stats.views.get_google_credentials_for_user", lambda user: credentials)
    monkeypatch.setattr("apps.gmail_stats.views.GmailClient", lambda value: ("gmail", value))
    synced = []
    monkeypatch.setattr(
        "apps.gmail_stats.views.sync_gmail_messages_for_user",
        lambda **kwargs: synced.append(kwargs) or {"proposals_created": 2},
    )

    response = client.post(reverse("gmail_stats:gmail_assistant_settings"), {"ai_enabled": "1"})

    settings = GmailAssistantSettings.objects.get(user=proposal.user)
    assert response.status_code == 302
    assert settings.ai_enabled is True
    assert settings.ai_consent_at is not None
    assert synced == [
        {
            "user": proposal.user,
            "gmail_client": ("gmail", credentials),
            "days": 180,
            "max_results_each": 500,
            "reanalyze_existing": True,
        }
    ]


@pytest.mark.django_db
def test_saving_enabled_ai_analysis_does_not_start_another_sync(client, proposal, monkeypatch):
    GmailAssistantSettings.objects.create(user=proposal.user, ai_enabled=True)
    client.force_login(proposal.user)
    monkeypatch.setattr(
        "apps.gmail_stats.views.sync_gmail_messages_for_user",
        lambda **kwargs: pytest.fail("sync must only run when AI is first enabled"),
    )

    response = client.post(reverse("gmail_stats:gmail_assistant_settings"), {"ai_enabled": "1"})

    assert response.status_code == 302


@pytest.mark.django_db
def test_application_detail_shows_only_its_gmail_metadata(client, proposal):
    client.force_login(proposal.user)

    response = client.get(reverse("applications:detail", args=[proposal.application.pk]))

    assert response.status_code == 200
    assert b"Gmail activity" in response.content
    assert proposal.message.subject.encode() in response.content


@pytest.mark.django_db
def test_create_application_proposal_displays_extracted_values(client, proposal):
    message = GmailMessage.objects.create(
        user=proposal.user,
        message_id="message-create",
        thread_id="thread-create",
        received_at=timezone.now(),
        subject="Application received",
    )
    analysis = GmailAnalysis.objects.create(
        user=proposal.user,
        message=message,
        event_type=GmailEventType.APPLICATION_RECEIVED,
        is_job_related=True,
    )
    created = ApplicationUpdateProposal.objects.create(
        user=proposal.user,
        message=message,
        analysis=analysis,
        proposal_type=ProposalType.CREATE_APPLICATION,
        changes={
            "application": {
                "operation": "create",
                "title": "Python Software Engineer",
                "company": "Smart Systems Hub GmbH",
                "location": "",
                "source": "other",
                "status": "applied",
                "applied_at": "2026-07-30T13:18:00+02:00",
            }
        },
    )
    client.force_login(proposal.user)

    response = client.get(reverse("gmail_stats:gmail_proposal_detail", args=[created.pk]))

    assert response.status_code == 200
    assert b"Python Software Engineer" in response.content
    assert b"Smart Systems Hub GmbH" in response.content
    assert b"Choose another application" not in response.content
