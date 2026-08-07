from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.applications.models import JobApplication
from apps.gmail_assistant.models import (
    AnalysisClassifier,
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailAssistantSettings,
    GmailEventType,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_stats.models import GmailMessage, GmailSyncState


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
    response = client.get(reverse("gmail_assistant:gmail_assistant"))

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

    response = client.get(reverse("gmail_assistant:gmail_assistant"))

    assert response.status_code == 200
    assert response.content.index(b"Newer Gmail update") < response.content.index(
        proposal.message.subject.encode()
    )


@pytest.mark.django_db
def test_pending_assistant_cards_include_client_side_filters(client, proposal):
    client.force_login(proposal.user)

    response = client.get(reverse("gmail_assistant:gmail_assistant"))

    assert response.status_code == 200
    assert b'id="pendingSearch"' in response.content
    assert b'id="pendingTypeFilter"' in response.content
    assert b'id="pendingSort"' in response.content
    assert b'data-event="general_update"' in response.content
    assert b'data-match="linked"' in response.content


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

    response = client.get(reverse("gmail_assistant:gmail_assistant"))

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

    response = client.get(reverse("gmail_assistant:gmail_assistant"), {"status": ProposalStatus.ACCEPTED})

    assert response.status_code == 200
    assert proposal.message.subject.encode() in response.content
    assert b"Pending Gmail update" not in response.content


@pytest.mark.django_db
def test_assistant_highlights_rejection_proposals(client, proposal):
    proposal.analysis.event_type = GmailEventType.REJECTION
    proposal.analysis.save(update_fields=["event_type"])
    client.force_login(proposal.user)

    response = client.get(reverse("gmail_assistant:gmail_assistant"))

    assert response.status_code == 200
    assert b"border-danger" in response.content
    assert b"bg-danger" in response.content


@pytest.mark.django_db
def test_assistant_cards_show_analysis_source_and_confidence(client, proposal):
    proposal.analysis.classifier = AnalysisClassifier.RULE_AI
    proposal.analysis.confidence = 96
    proposal.analysis.save(update_fields=["classifier", "confidence"])
    client.force_login(proposal.user)

    response = client.get(reverse("gmail_assistant:gmail_assistant"))

    assert response.status_code == 200
    assert b"Analysis:" in response.content
    assert b"Confidence:" in response.content
    assert b"96%" in response.content


@pytest.mark.django_db
def test_assistant_explains_initial_ai_analysis_delay(client, proposal):
    client.force_login(proposal.user)

    response = client.get(reverse("gmail_assistant:gmail_assistant"))

    assert response.status_code == 200
    assert b"depends on the selected period and number of new messages" in response.content
    assert b"Daily AI email limit (per user)" in response.content
    assert b"FAQ" in response.content
    assert b'aiAnalysisSpinner' in response.content
    assert b'aiAnalysisSync' in response.content
    assert b'gmailSyncPeriodModal' in response.content
    assert b"only when AI analysis is enabled" in response.content
    assert b"Previously synced messages are skipped" in response.content
    assert b'syncNewGmail' in response.content
    assert b'devReanalyzeGmail' not in response.content
    for days in (b'"1"', b'"7"', b'"30"', b'"90"', b'"180"'):
        assert b"value=" + days in response.content
    assert b'new URLSearchParams({days})' in response.content
    assert b'params.set("reanalyze", "1")' in response.content
    assert b'aiAnalysisSave' not in response.content
    assert b"toggle.disabled" not in response.content
    assert reverse("gmail_assistant:gmail_assistant").encode() in response.content


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_DEV_TOOLS=True, TELEGRAM_OWNER_EMAIL="owner@example.com")
def test_assistant_shows_reanalysis_only_in_development_mode(client, proposal):
    client.force_login(proposal.user)

    response = client.get(reverse("gmail_assistant:gmail_assistant"))

    assert response.status_code == 200
    assert b'devReanalyzeGmail' in response.content
    assert b'devReanalyzeDays' in response.content
    assert b">Reanalyze<" in response.content


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_DEV_TOOLS=True, TELEGRAM_OWNER_EMAIL="owner@example.com")
def test_development_tools_are_hidden_from_non_owner(client, proposal, django_user_model):
    other = django_user_model.objects.create_user("other", email="other@example.com")
    client.force_login(other)

    response = client.get(reverse("gmail_assistant:gmail_assistant"))

    assert response.status_code == 200
    assert b"Development tools:" not in response.content
    assert b"devReanalyzeGmail" not in response.content


@pytest.mark.django_db
def test_assistant_shows_safe_last_sync_status(client, proposal):
    GmailAssistantSettings.objects.create(
        user=proposal.user,
        last_successful_run_at=timezone.now(),
        last_error_at=timezone.now(),
        last_error_message="RuntimeError",
    )
    client.force_login(proposal.user)

    response = client.get(reverse("gmail_assistant:gmail_assistant"))

    assert response.status_code == 200
    assert b"Last successful Gmail sync" in response.content
    assert b"latest Gmail sync needs attention" in response.content
    assert b"RuntimeError" not in response.content


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_DEV_TOOLS=True)
def test_write_endpoints_reject_get_requests(client, proposal):
    client.force_login(proposal.user)
    urls = [
        reverse("gmail_assistant:accept_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_assistant:edit_accept_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_assistant:assign_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_assistant:reject_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_assistant:ignore_gmail_proposal", args=[proposal.pk]),
        reverse("gmail_assistant:bulk_create_gmail_applications"),
        reverse("gmail_assistant:gmail_assistant_settings"),
        reverse("gmail_assistant:reset_ai_daily_limit"),
        reverse("gmail_assistant:reset_gmail_assistant"),
    ]

    assert all(client.get(url).status_code == 405 for url in urls)


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_DEV_TOOLS=True, TELEGRAM_OWNER_EMAIL="owner@example.com")
def test_dev_reset_removes_only_current_users_gmail_assistant_data(client, proposal):
    GmailSyncState.objects.create(user=proposal.user, last_synced_at=timezone.now())
    client.force_login(proposal.user)

    response = client.post(reverse("gmail_assistant:reset_gmail_assistant"))

    assert response.status_code == 302
    assert not GmailMessage.objects.filter(user=proposal.user).exists()
    assert not ApplicationUpdateProposal.objects.filter(user=proposal.user).exists()
    assert not GmailSyncState.objects.filter(user=proposal.user).exists()
    assert not JobApplication.objects.filter(pk=proposal.application_id, user=proposal.user).exists()


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_DEV_TOOLS=False)
def test_dev_reset_endpoint_is_hidden_without_dev_tools(client, proposal):
    client.force_login(proposal.user)

    response = client.post(reverse("gmail_assistant:reset_gmail_assistant"))

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_DEV_TOOLS=True, TELEGRAM_OWNER_EMAIL="owner@example.com")
def test_dev_can_reset_only_own_daily_ai_limit(client, proposal):
    GmailAssistantSettings.objects.create(user=proposal.user)
    client.force_login(proposal.user)

    response = client.post(reverse("gmail_assistant:reset_ai_daily_limit"), follow=True)

    assistant_settings = GmailAssistantSettings.objects.get(user=proposal.user)
    assert response.status_code == 200
    assert assistant_settings.ai_daily_usage_reset_at is not None
    assert b"AI limit was reset for this user" in response.content


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_DEV_TOOLS=True, TELEGRAM_OWNER_EMAIL="owner@example.com")
def test_dev_reset_endpoint_is_hidden_from_non_owner(client, proposal, django_user_model):
    other = django_user_model.objects.create_user("other", email="other@example.com")
    client.force_login(other)

    response = client.post(reverse("gmail_assistant:reset_gmail_assistant"))

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

    response = getattr(client, method)(reverse(f"gmail_assistant:{url_name}", args=[proposal.pk]), data=data)

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

    assistant = client.get(reverse("gmail_assistant:gmail_assistant"))
    application = client.get(reverse("applications:detail", args=[proposal.application_id]))

    assert assistant.status_code == 200
    assert proposal.message.subject.encode() not in assistant.content
    assert application.status_code == 404


@pytest.mark.django_db
def test_accept_endpoint_applies_a_pending_proposal(client, proposal):
    client.force_login(proposal.user)

    response = client.post(
        reverse("gmail_assistant:accept_gmail_proposal", args=[proposal.pk]),
        {"review_note": "Status confirmed after recruiter call."},
    )

    assert response.status_code == 302
    assert response.url == reverse("gmail_assistant:gmail_assistant")
    proposal.refresh_from_db()
    proposal.application.refresh_from_db()
    assert proposal.status == ProposalStatus.ACCEPTED
    assert proposal.review_note == "Status confirmed after recruiter call."
    assert proposal.application.status == "replied"


@pytest.mark.django_db
def test_bulk_create_only_creates_eligible_high_confidence_ai_proposals(client, proposal):
    proposal.application = None
    proposal.proposal_type = ProposalType.CREATE_APPLICATION
    proposal.changes = {
        "application": {
            "operation": "create",
            "title": "AI Developer",
            "company": "Example AI GmbH",
            "source": "other",
            "status": "applied",
            "applied_at": timezone.now().isoformat(),
        }
    }
    proposal.analysis.classifier = AnalysisClassifier.AI
    proposal.analysis.confidence = 75
    proposal.analysis.save(update_fields=["classifier", "confidence"])
    proposal.save(update_fields=["application", "proposal_type", "changes"])
    client.force_login(proposal.user)

    response = client.post(reverse("gmail_assistant:bulk_create_gmail_applications"), follow=True)

    assert response.status_code == 200
    assert JobApplication.objects.filter(user=proposal.user, title="AI Developer", company="Example AI GmbH").exists()
    proposal.refresh_from_db()
    assert proposal.status == ProposalStatus.ACCEPTED
    assert b"Created 1 applications from high-confidence AI suggestions." in response.content


@pytest.mark.django_db
def test_bulk_create_leaves_possible_duplicates_pending(client, proposal):
    existing_application = proposal.application
    proposal.application = None
    proposal.proposal_type = ProposalType.CREATE_APPLICATION
    proposal.changes = {
        "application": {
            "operation": "create",
            "title": existing_application.title,
            "company": existing_application.company,
        }
    }
    proposal.analysis.classifier = AnalysisClassifier.AI
    proposal.analysis.confidence = 90
    proposal.analysis.save(update_fields=["classifier", "confidence"])
    proposal.save(update_fields=["application", "proposal_type", "changes"])
    client.force_login(proposal.user)

    response = client.post(reverse("gmail_assistant:bulk_create_gmail_applications"), follow=True)

    proposal.refresh_from_db()
    assert response.status_code == 200
    assert proposal.status == ProposalStatus.PENDING
    assert b"1 possible duplicates were left pending for review." in response.content


@pytest.mark.django_db
def test_assign_endpoint_accepts_only_current_users_application(client, proposal, django_user_model):
    other = django_user_model.objects.create_user("other", email="other@example.com")
    other_application = JobApplication.objects.create(user=other, company="Other", title="Role")
    client.force_login(proposal.user)

    response = client.post(
        reverse("gmail_assistant:assign_gmail_proposal", args=[proposal.pk]),
        {"application_id": other_application.pk},
    )

    assert response.status_code == 404
    proposal.refresh_from_db()
    assert proposal.match_method == ""


@pytest.mark.django_db
def test_enabling_ai_analysis_only_saves_the_setting(client, proposal):
    client.force_login(proposal.user)

    response = client.post(
        reverse("gmail_assistant:gmail_assistant_settings"),
        {"ai_enabled": "1"},
        follow=True,
    )

    settings = GmailAssistantSettings.objects.get(user=proposal.user)
    assert response.status_code == 200
    assert settings.ai_enabled is True
    assert settings.ai_consent_at is not None
    assert b"AI analysis setting updated." in response.content
    assert b"Gmail synced" not in response.content


@pytest.mark.django_db
def test_auto_apply_setting_requires_enabled_ai_analysis(client, proposal):
    client.force_login(proposal.user)

    client.post(
        reverse("gmail_assistant:gmail_assistant_settings"),
        {"ai_enabled": "1", "auto_apply_enabled": "1"},
    )
    settings = GmailAssistantSettings.objects.get(user=proposal.user)
    assert settings.auto_apply_enabled is True
    assert settings.auto_apply_consent_at is not None

    client.post(reverse("gmail_assistant:gmail_assistant_settings"), {"auto_apply_enabled": "1"})
    settings.refresh_from_db()
    assert settings.ai_enabled is False
    assert settings.auto_apply_enabled is False


@pytest.mark.django_db
def test_disabling_ai_analysis_uses_absent_checkbox_value(client, proposal):
    GmailAssistantSettings.objects.create(user=proposal.user, ai_enabled=True)
    client.force_login(proposal.user)

    response = client.post(reverse("gmail_assistant:gmail_assistant_settings"), {})

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

    response = client.get(reverse("gmail_assistant:gmail_proposal_detail", args=[created.pk]))

    assert response.status_code == 200
    assert b"Python Software Engineer" in response.content
    assert b"Smart Systems Hub GmbH" in response.content
    assert b"Link the correct application" in response.content
    assert b"Check the source email" in response.content
    assert b"Verify the proposed change" in response.content


@pytest.mark.django_db
def test_review_page_shows_sender_excerpt_and_requires_link_for_action(client, proposal):
    proposal.application = None
    proposal.proposal_type = ProposalType.ACTION_REQUIRED
    proposal.changes = {"action": {"text": "Confirm here: https://example.org/confirm", "deadline_at": None}}
    proposal.message.from_email = "jobs@example.org"
    proposal.message.snippet = "Complete the requested confirmation."
    proposal.message.save(update_fields=["from_email", "snippet"])
    proposal.save(update_fields=["application", "proposal_type", "changes"])
    client.force_login(proposal.user)

    response = client.get(reverse("gmail_assistant:gmail_proposal_detail", args=[proposal.pk]))

    assert response.status_code == 200
    assert b"jobs@example.org" in response.content
    assert b"Complete the requested confirmation." in response.content
    assert b"https://example.org/confirm" in response.content
    assert b"Complete step 4 before accepting this proposal." in response.content
