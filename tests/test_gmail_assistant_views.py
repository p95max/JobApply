from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import override_settings
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
    GmailSyncState,
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
def test_assistant_lists_newest_email_first(client, proposal):
    newer_message = GmailMessage.objects.create(
        user=proposal.user,
        message_id="message-newer",
        thread_id="thread-newer",
        received_at=proposal.message.received_at + timedelta(hours=1),
        subject="Newer Gmail update",
    )
    newer_analysis = GmailAnalysis.objects.create(
        user=proposal.user,
        message=newer_message,
        event_type=GmailEventType.GENERAL_UPDATE,
        is_job_related=True,
    )
    ApplicationUpdateProposal.objects.create(
        user=proposal.user,
        message=newer_message,
        analysis=newer_analysis,
        application=proposal.application,
        proposal_type=ProposalType.UPDATE_APPLICATION,
    )
    client.force_login(proposal.user)

    response = client.get(reverse("gmail_stats:gmail_assistant"))

    assert response.status_code == 200
    assert response.content.index(b"Newer Gmail update") < response.content.index(
        proposal.message.subject.encode()
    )


@pytest.mark.django_db
def test_assistant_displays_a_count_for_each_proposal_status(client, proposal):
    proposal.status = ProposalStatus.ACCEPTED
    proposal.save(update_fields=["status"])
    ApplicationUpdateProposal.objects.create(
        user=proposal.user,
        message=proposal.message,
        analysis=proposal.analysis,
        application=proposal.application,
        proposal_type=ProposalType.UPDATE_APPLICATION,
        status=ProposalStatus.ACCEPTED,
    )
    client.force_login(proposal.user)

    response = client.get(reverse("gmail_stats:gmail_assistant"))

    assert response.status_code == 200
    assert b"Pending <span class=\"badge rounded-pill text-bg-light ms-1\">0</span>" in response.content
    assert b"Accepted <span class=\"badge rounded-pill text-bg-light ms-1\">2</span>" in response.content


@pytest.mark.django_db
def test_assistant_filters_cards_by_selected_status(client, proposal):
    proposal.status = ProposalStatus.ACCEPTED
    proposal.save(update_fields=["status"])
    pending_message = GmailMessage.objects.create(
        user=proposal.user,
        message_id="pending-message",
        thread_id="pending-thread",
        received_at=proposal.message.received_at + timedelta(hours=1),
        subject="Pending Gmail update",
    )
    pending_analysis = GmailAnalysis.objects.create(
        user=proposal.user,
        message=pending_message,
        event_type=GmailEventType.GENERAL_UPDATE,
        is_job_related=True,
    )
    ApplicationUpdateProposal.objects.create(
        user=proposal.user,
        message=pending_message,
        analysis=pending_analysis,
        application=proposal.application,
        proposal_type=ProposalType.UPDATE_APPLICATION,
    )
    client.force_login(proposal.user)

    response = client.get(reverse("gmail_stats:gmail_assistant"), {"status": ProposalStatus.ACCEPTED})

    assert response.status_code == 200
    assert proposal.message.subject.encode() in response.content
    assert b"Pending Gmail update" not in response.content


@pytest.mark.django_db
def test_assistant_highlights_rejection_proposals(client, proposal):
    proposal.analysis.event_type = GmailEventType.REJECTION
    proposal.analysis.save(update_fields=["event_type"])
    client.force_login(proposal.user)

    response = client.get(reverse("gmail_stats:gmail_assistant"))

    assert response.status_code == 200
    assert b"border-danger" in response.content
    assert b"bg-danger" in response.content


@pytest.mark.django_db
def test_assistant_explains_initial_ai_analysis_delay(client, proposal):
    client.force_login(proposal.user)

    response = client.get(reverse("gmail_stats:gmail_assistant"))

    assert response.status_code == 200
    assert b"can take about 30 seconds" in response.content
    assert b"FAQ" in response.content
    assert b'aiAnalysisSpinner' in response.content
    assert b'aiAnalysisSync' in response.content
    assert b'aiAnalysisSave' not in response.content
    assert b"toggle.disabled" not in response.content
    assert b'services-dropdown' in response.content
    assert reverse("gmail_stats:gmail_assistant").encode() in response.content


@pytest.mark.django_db
def test_assistant_shows_safe_last_sync_status(client, proposal):
    GmailAssistantSettings.objects.create(
        user=proposal.user,
        last_successful_run_at=timezone.now(),
        last_error_at=timezone.now(),
        last_error_message="RuntimeError",
    )
    client.force_login(proposal.user)

    response = client.get(reverse("gmail_stats:gmail_assistant"))

    assert response.status_code == 200
    assert b"Last successful Gmail sync" in response.content
    assert b"latest Gmail sync needs attention" in response.content
    assert b"RuntimeError" not in response.content


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_DEV_TOOLS=True)
def test_write_endpoints_reject_get_requests(client, proposal):
    client.force_login(proposal.user)
    urls = [
        reverse("gmail_stats:accept_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_stats:edit_accept_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_stats:assign_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_stats:reject_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_stats:ignore_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_stats:gmail_assistant_settings"),
        reverse("gmail_stats:reset_gmail_assistant"),
    ]

    assert all(client.get(url).status_code == 405 for url in urls)


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_DEV_TOOLS=True)
def test_dev_reset_removes_only_current_users_gmail_assistant_data(client, proposal):
    GmailSyncState.objects.create(user=proposal.user, last_synced_at=timezone.now())
    client.force_login(proposal.user)

    response = client.post(reverse("gmail_stats:reset_gmail_assistant"))

    assert response.status_code == 302
    assert not GmailMessage.objects.filter(user=proposal.user).exists()
    assert not ApplicationUpdateProposal.objects.filter(user=proposal.user).exists()
    assert not GmailSyncState.objects.filter(user=proposal.user).exists()
    assert not JobApplication.objects.filter(pk=proposal.application_id, user=proposal.user).exists()


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_DEV_TOOLS=False)
def test_dev_reset_endpoint_is_hidden_without_dev_tools(client, proposal):
    client.force_login(proposal.user)

    response = client.post(reverse("gmail_stats:reset_gmail_assistant"))

    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("url_name", "method", "data"),
    [
        ("gmail_proposal_detail", "get", None),
        ("accept_gmail_proposal", "post", None),
        ("edit_accept_gmail_proposal", "post", {"title": "Changed"}),
        ("assign_gmail_proposal", "post", {"application_id": 1}),
        ("reject_gmail_proposal", "post", None),
        ("ignore_gmail_proposal", "post", None),
    ],
)
def test_user_cannot_access_another_users_proposal(client, proposal, django_user_model, url_name, method, data):
    other = django_user_model.objects.create_user("other", email="other@example.com")
    UserProfile.objects.create(user=other, google_data_access_consent=True)
    client.force_login(other)

    response = getattr(client, method)(reverse(f"gmail_stats:{url_name}", args=[proposal.pk]), data=data)

    assert response.status_code == 404
    proposal.refresh_from_db()
    assert proposal.status == ProposalStatus.PENDING


@pytest.mark.django_db
def test_user_cannot_see_another_users_proposal_in_assistant_or_application_detail(
    client, proposal, django_user_model
):
    other = django_user_model.objects.create_user("other", email="other@example.com")
    UserProfile.objects.create(user=other, google_data_access_consent=True)
    client.force_login(other)

    assistant = client.get(reverse("gmail_stats:gmail_assistant"))
    application = client.get(reverse("applications:detail", args=[proposal.application_id]))

    assert assistant.status_code == 200
    assert proposal.message.subject.encode() not in assistant.content
    assert application.status_code == 404


@pytest.mark.django_db
def test_accept_endpoint_applies_a_pending_proposal(client, proposal):
    client.force_login(proposal.user)

    response = client.post(reverse("gmail_stats:accept_gmail_proposal", args=[proposal.pk]))

    assert response.status_code == 302
    assert response.url == reverse("gmail_stats:gmail_assistant")
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
def test_initial_ai_sync_does_not_expose_gmail_error_details(client, proposal, monkeypatch):
    secret = "refresh-token-should-not-reach-the-browser"
    client.force_login(proposal.user)
    monkeypatch.setattr("apps.gmail_stats.views.get_google_credentials_for_user", lambda user: object())
    monkeypatch.setattr("apps.gmail_stats.views.GmailClient", lambda credentials: object())
    monkeypatch.setattr(
        "apps.gmail_stats.views.sync_gmail_messages_for_user",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError(secret)),
    )

    response = client.post(
        reverse("gmail_stats:gmail_assistant_settings"),
        {"ai_enabled": "1"},
        follow=True,
    )

    assert response.status_code == 200
    assert b"Gmail sync failed. Try again later." in response.content
    assert secret.encode() not in response.content


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
def test_disabling_ai_analysis_uses_absent_checkbox_value(client, proposal):
    GmailAssistantSettings.objects.create(user=proposal.user, ai_enabled=True)
    client.force_login(proposal.user)

    response = client.post(reverse("gmail_stats:gmail_assistant_settings"), {})

    settings = GmailAssistantSettings.objects.get(user=proposal.user)
    assert response.status_code == 302
    assert settings.ai_enabled is False


@pytest.mark.django_db
def test_application_detail_shows_only_its_gmail_metadata(client, proposal):
    client.force_login(proposal.user)

    response = client.get(reverse("applications:detail", args=[proposal.application.pk]))

    assert response.status_code == 200
    assert b"Gmail activity" in response.content
    assert b"gmail-timeline" in response.content
    assert proposal.message.subject.encode() in response.content


@pytest.mark.django_db
def test_application_detail_highlights_a_rejection(client, proposal):
    proposal.analysis.event_type = GmailEventType.REJECTION
    proposal.analysis.save(update_fields=["event_type"])
    client.force_login(proposal.user)

    response = client.get(reverse("applications:detail", args=[proposal.application.pk]))

    assert response.status_code == 200
    assert b"gmail-timeline-item is-rejection" in response.content
    assert b"text-danger" in response.content
    assert b"Rejection" in response.content


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
