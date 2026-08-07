from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.applications.models import JobApplication
from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    AnalysisClassifier,
    GmailAnalysis,
    GmailAssistantSettings,
    GmailEventType,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_assistant.services.ai_analyzer import (
    AIAnalysisContext,
    AIAnalyzerConfig,
    AIAnalyzerError,
    AIExtraction,
    InterviewExtraction,
)
from apps.gmail_assistant.services.sync import sync_gmail_messages_for_user
from apps.gmail_stats.models import GmailMessage, GmailProcessingStatus, GmailSyncState


def _body(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def message(*, sender: str, subject: str, text: str, recipient: str = "user@example.com") -> dict:
    return {
        "threadId": "thread-1",
        "internalDate": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
        "snippet": text[:100],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "To", "value": recipient},
            ],
            "body": {"data": _body(text)},
        },
    }


class FakeGmailClient:
    def __init__(self, messages: dict[str, dict]):
        self.messages = messages

    def list_message_ids(self, query: str, max_results: int = 500) -> list[str]:
        assert "-from:me" in query
        return list(self.messages)

    def get_profile_email(self) -> str:
        return "user@example.com"

    def get_message_full(self, message_id: str) -> dict:
        return self.messages[message_id]


class FakeAnalyzer:
    config = AIAnalyzerConfig(enabled=True, api_key="test-key", model="gpt-4.1-mini")

    def __init__(self):
        self.calls: list[AIAnalysisContext] = []

    def analyze(self, email, context: AIAnalysisContext) -> AIExtraction:
        self.calls.append(context)
        return AIExtraction(
            is_job_related=True,
            event_type="interview_invitation",
            company="Example GmbH",
            position_title="Python Developer",
            location="Leipzig",
            external_application_id=None,
            proposed_status="interview",
            recruiter_name="Recruiter",
            recruiter_email="recruiter@example.org",
            summary="Interview invitation.",
            action_required=True,
            action_text="Confirm the interview time.",
            deadline_at=None,
            interview=InterviewExtraction(
                starts_at="2026-08-06T09:00:00+02:00",
                ends_at=None,
                timezone="Europe/Berlin",
                mode="video",
                location="Video call",
                meeting_url=None,
            ),
            confidence=95,
            evidence=("Interview invitation",),
        )


class FailingAnalyzer(FakeAnalyzer):
    def analyze(self, email, context: AIAnalysisContext) -> AIExtraction:
        raise AIAnalyzerError("provider unavailable")


class MissingKeyAnalyzer(FakeAnalyzer):
    config = AIAnalyzerConfig(enabled=True, api_key="", model="gpt-4.1-mini")

    def analyze(self, email, context: AIAnalysisContext) -> AIExtraction:
        raise AssertionError("AI must not run without an API key")


@pytest.mark.django_db
def test_manual_sent_import_creates_a_myself_sent_application_proposal(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    GmailSyncState.objects.create(user=user, last_synced_at=datetime.now(timezone.utc))

    class SentQueryClient(FakeGmailClient):
        def __init__(self, messages):
            super().__init__(messages)
            self.queries = []

        def list_message_ids(self, query: str, max_results: int = 500) -> list[str]:
            self.queries.append(query)
            return list(self.messages)

    client = SentQueryClient(
        {
            "sent-application": message(
                sender="user@example.com",
                recipient="jobs@doma-personal.de",
                subject="Application for Python Developer",
                text="I would like to apply for the Python Developer position.",
            )
        }
    )

    result = sync_gmail_messages_for_user(
        user=user,
        gmail_client=client,
        days=30,
        include_sent=True,
    )

    analysis = GmailAnalysis.objects.get(user=user)
    proposal = ApplicationUpdateProposal.objects.get(user=user)
    assert any("in:sent" in query and "newer_than:30d" in query for query in client.queries)
    assert result["outbound_imported"] == 1
    assert analysis.event_type == GmailEventType.APPLICATION_SENT
    assert analysis.message.direction == "outbound"
    assert proposal.proposal_type == ProposalType.CREATE_APPLICATION
    assert proposal.changes["application"]["company"] == "Doma Personal"
    assert proposal.changes["application"]["title"] == "Python Developer"


@pytest.mark.django_db
def test_rule_only_pipeline_saves_analysis_without_openai(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    client = FakeGmailClient(
        {
            "message-1": message(
                sender="recruiter@example.org",
                subject="Update on your application",
                text="We will get back to you about your application.",
            )
        }
    )

    result = sync_gmail_messages_for_user(user=user, gmail_client=client)
    analysis = GmailAnalysis.objects.get(user=user)
    assert result["analyzed_by_rules"] == 1
    assert result["analyses_created"] == 1
    assert analysis.classifier == AnalysisClassifier.RULE
    assert analysis.message.processing_status == GmailProcessingStatus.ANALYZED


@pytest.mark.django_db
def test_successful_sync_clears_the_previous_safe_error(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    settings = GmailAssistantSettings.objects.create(
        user=user,
        last_error_at=datetime.now(timezone.utc),
        last_error_message="message_processing_failed",
    )
    client = FakeGmailClient(
        {
            "message-1": message(
                sender="recruiter@example.org",
                subject="Application update",
                text="We will get back to you about your application.",
            )
        }
    )

    result = sync_gmail_messages_for_user(user=user, gmail_client=client)

    settings.refresh_from_db()
    assert result["failed"] == 0
    assert settings.last_successful_run_at is not None
    assert settings.last_error_at is None
    assert settings.last_error_message == ""


@pytest.mark.django_db
def test_ai_pipeline_uses_fake_analyzer_and_creates_pending_proposals(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    JobApplication.objects.create(user=user, company="Example GmbH", title="Python Developer")
    GmailAssistantSettings.objects.create(user=user, ai_enabled=True)
    analyzer = FakeAnalyzer()
    client = FakeGmailClient(
        {
            "message-1": message(
                sender="recruiter@example.org",
                subject="Interview invitation",
                text="We would like to invite you to an interview for your application.",
            )
        }
    )

    result = sync_gmail_messages_for_user(user=user, gmail_client=client, ai_analyzer=analyzer)

    analysis = GmailAnalysis.objects.get(user=user)
    assert result["analyzed_by_ai"] == 1
    assert result["analyses_created"] == 1
    assert result["proposals_created"] == 3
    assert len(analyzer.calls) == 1
    assert analysis.classifier == AnalysisClassifier.AI
    assert analysis.model_name == "gpt-4.1-mini"
    assert analysis.proposals.filter(status=ProposalStatus.PENDING).count() == 3


@pytest.mark.django_db
def test_first_ai_opt_in_reanalyzes_previously_synced_messages(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    client = FakeGmailClient(
        {
            "message-1": message(
                sender="recruiter@example.org",
                subject="Interview invitation",
                text="We would like to invite you to an interview for your application.",
            )
        }
    )
    GmailAssistantSettings.objects.create(user=user, ai_enabled=True)

    sync_gmail_messages_for_user(user=user, gmail_client=client, ai_analyzer=MissingKeyAnalyzer())
    analyzer = FakeAnalyzer()
    result = sync_gmail_messages_for_user(
        user=user,
        gmail_client=client,
        ai_analyzer=analyzer,
        reanalyze_existing=True,
    )

    analysis = GmailAnalysis.objects.get(user=user, message__message_id="message-1")
    assert result["skipped_existing"] == 0
    assert len(analyzer.calls) == 1
    assert analysis.classifier == AnalysisClassifier.AI


@pytest.mark.django_db
def test_manual_reanalysis_includes_cached_messages_outside_incremental_window(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    old_message = GmailMessage.objects.create(
        user=user,
        message_id="old-message",
        thread_id="old-thread",
        received_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        subject="Application received",
    )
    old_analysis = GmailAnalysis.objects.create(
        user=user,
        message=old_message,
        event_type=GmailEventType.APPLICATION_RECEIVED,
        is_job_related=True,
        extracted_data={"company": "Stepstone", "position_title": "Python Software Engineer"},
    )
    ApplicationUpdateProposal.objects.create(
        user=user,
        message=old_message,
        analysis=old_analysis,
        proposal_type=ProposalType.CREATE_APPLICATION,
        changes={"application": {"company": "Stepstone", "title": "Python Software Engineer"}},
    )
    GmailSyncState.objects.create(user=user, last_synced_at=datetime.now(timezone.utc))

    class EmptyListingClient(FakeGmailClient):
        def list_message_ids(self, query: str, max_results: int = 500) -> list[str]:
            return []

    client = EmptyListingClient(
        {
            "old-message": message(
                sender="no-reply@stepstone.de",
                subject="Application received",
                text="We received your application.",
            )
        }
    )

    sync_gmail_messages_for_user(user=user, gmail_client=client, reanalyze_existing=True)

    assert not ApplicationUpdateProposal.objects.filter(
        user=user,
        message=old_message,
        proposal_type=ProposalType.CREATE_APPLICATION,
        status=ProposalStatus.PENDING,
    ).exists()


@pytest.mark.django_db
def test_outbound_and_high_confidence_noise_do_not_call_ai(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    GmailAssistantSettings.objects.create(user=user, ai_enabled=True)
    analyzer = FakeAnalyzer()
    client = FakeGmailClient(
        {
            "outbound": message(
                sender="user@example.com",
                subject="Application submitted",
                text="My application has been submitted.",
                recipient="recruiter@example.org",
            ),
            "noise": message(
                sender="news@example.org",
                subject="Newsletter",
                text="Unsubscribe from this job alert newsletter.",
            ),
        }
    )

    result = sync_gmail_messages_for_user(user=user, gmail_client=client, ai_analyzer=analyzer)

    assert analyzer.calls == []
    assert result["outbound_ignored"] == 1
    assert result["ignored_noise"] == 1


@pytest.mark.django_db
def test_ai_failure_keeps_the_rule_result_and_does_not_abort_the_batch(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    GmailAssistantSettings.objects.create(user=user, ai_enabled=True)
    client = FakeGmailClient(
        {
            "message-1": message(
                sender="recruiter@example.org",
                subject="Interview invitation",
                text="We would like to invite you to an interview for your application.",
            )
        }
    )

    result = sync_gmail_messages_for_user(
        user=user,
        gmail_client=client,
        ai_analyzer=FailingAnalyzer(),
    )

    analysis = GmailAnalysis.objects.get(user=user)
    assert result["failed"] == 0
    assert result["analyzed_by_rules"] == 1
    assert analysis.classifier == AnalysisClassifier.RULE
    assert analysis.message.processing_status == GmailProcessingStatus.ANALYZED
    assert analysis.message.processing_error == "AIAnalyzerError"


@pytest.mark.django_db
def test_missing_api_key_keeps_the_pipeline_in_rule_only_mode(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    GmailAssistantSettings.objects.create(user=user, ai_enabled=True)
    client = FakeGmailClient(
        {
            "message-1": message(
                sender="recruiter@example.org",
                subject="Interview invitation",
                text="We would like to invite you to an interview for your application.",
            )
        }
    )

    result = sync_gmail_messages_for_user(user=user, gmail_client=client, ai_analyzer=MissingKeyAnalyzer())

    assert result["analyzed_by_ai"] == 0
    assert result["analyzed_by_rules"] == 1


@pytest.mark.django_db
def test_sync_api_reports_missing_gmail_readonly_permission(client, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    UserProfile.objects.create(user=user, google_data_access_consent=True)

    class PermissionDeniedGmailClient:
        def __init__(self, credentials):
            self.credentials = credentials

        def list_message_ids(self, query: str, max_results: int = 500) -> list[str]:
            raise RuntimeError("insufficientPermissions")

    monkeypatch.setattr("apps.gmail_stats.views.get_google_credentials_for_user", lambda user: object())
    monkeypatch.setattr("apps.gmail_stats.views.GmailClient", PermissionDeniedGmailClient)

    client.force_login(user)
    response = client.post(reverse("gmail_stats:gmail_sync_api"))

    assert response.status_code == 403
    assert "gmail.readonly" in response.json()["error"]


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_DEV_TOOLS=True, TELEGRAM_OWNER_EMAIL="user@example.com")
@pytest.mark.parametrize("days", [1, 7, 30, 90, 180])
def test_sync_api_passes_selected_period_to_assistant(client, django_user_model, monkeypatch, days):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    UserProfile.objects.create(user=user, google_data_access_consent=True)
    preflight_queries = []
    synced = []

    class PreflightGmailClient:
        def list_message_ids(self, query: str, max_results: int = 500) -> list[str]:
            preflight_queries.append(query)
            return []

    monkeypatch.setattr("apps.gmail_stats.views.get_google_credentials_for_user", lambda user: object())
    monkeypatch.setattr("apps.gmail_stats.views.GmailClient", lambda credentials: PreflightGmailClient())
    monkeypatch.setattr(
        "apps.gmail_stats.views.sync_gmail_messages_for_user",
        lambda **kwargs: synced.append(kwargs) or {"proposals_created": 0},
    )

    client.force_login(user)
    response = client.post(reverse("gmail_stats:gmail_sync_api") + f"?days={days}&reanalyze=1")

    assert response.status_code == 200
    assert preflight_queries == [f"newer_than:{min(days, 7)}d"]
    assert len(synced) == 1
    assert synced[0]["user"] == user
    assert isinstance(synced[0]["gmail_client"], PreflightGmailClient)
    assert synced[0]["days"] == days
    assert synced[0]["max_results_each"] == 500
    assert synced[0]["reanalyze_existing"] is True


@pytest.mark.django_db
@override_settings(GMAIL_ASSISTANT_DEV_TOOLS=True, TELEGRAM_OWNER_EMAIL="owner@example.com")
def test_sync_api_hides_reanalysis_from_non_owner(client, django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    client.force_login(user)

    response = client.post(reverse("gmail_stats:gmail_sync_api") + "?days=7&reanalyze=1")

    assert response.status_code == 404


@pytest.mark.django_db
def test_sync_api_reports_disabled_gmail_api(client, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    UserProfile.objects.create(user=user, google_data_access_consent=True)

    class DisabledGmailClient:
        def __init__(self, credentials):
            self.credentials = credentials

        def list_message_ids(self, query: str, max_results: int = 500) -> list[str]:
            raise RuntimeError("accessNotConfigured")

    monkeypatch.setattr("apps.gmail_stats.views.get_google_credentials_for_user", lambda user: object())
    monkeypatch.setattr("apps.gmail_stats.views.GmailClient", DisabledGmailClient)
    client.force_login(user)

    response = client.post(reverse("gmail_stats:gmail_sync_api"))

    assert response.status_code == 403
    assert "Gmail API is disabled" in response.json()["error"]


@pytest.mark.django_db
def test_sync_api_hides_unexpected_gmail_error_details(client, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    UserProfile.objects.create(user=user, google_data_access_consent=True)
    secret = "access-token-should-not-reach-the-browser"

    class FailingGmailClient:
        def __init__(self, credentials):
            self.credentials = credentials

        def list_message_ids(self, query: str, max_results: int = 500) -> list[str]:
            raise RuntimeError(secret)

    monkeypatch.setattr("apps.gmail_stats.views.get_google_credentials_for_user", lambda user: object())
    monkeypatch.setattr("apps.gmail_stats.views.GmailClient", FailingGmailClient)
    client.force_login(user)

    response = client.post(reverse("gmail_stats:gmail_sync_api"))

    assert response.status_code == 403
    assert response.json()["error"] == "Gmail access failed. Reconnect Google and try again."
    assert secret not in response.json()["error"]
