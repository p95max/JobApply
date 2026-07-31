from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.applications.models import JobApplication
from apps.gmail_stats.models import (
    AnalysisClassifier,
    GmailAnalysis,
    GmailAssistantSettings,
    GmailProcessingStatus,
    ProposalStatus,
)
from apps.gmail_stats.services.ai_analyzer import (
    AIAnalysisContext,
    AIAnalyzerConfig,
    AIAnalyzerError,
    AIExtraction,
    InterviewExtraction,
)
from apps.gmail_stats.services.sync import sync_gmail_messages_for_user


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
    assert result["proposals_created"] == 2
    assert len(analyzer.calls) == 1
    assert analysis.classifier == AnalysisClassifier.RULE_AI
    assert analysis.model_name == "gpt-4.1-mini"
    assert analysis.proposals.filter(status=ProposalStatus.PENDING).count() == 2


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
