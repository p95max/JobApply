from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.applications.models import JobApplication
from apps.gmail_assistant.models import (
    AnalysisClassifier,
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailEventType,
    ProposalType,
)
from apps.gmail_stats.models import GmailMessage


AUDIT_KEY = "ai-audit-test-key"


def _staff_user():
    return get_user_model().objects.create_user(
        "audit-staff",
        email="audit-staff@example.com",
        is_staff=True,
    )


def _ai_proposal(*, user, classifier=AnalysisClassifier.AI):
    application = JobApplication.objects.create(
        user=user,
        company="Example GmbH",
        title="Python Developer",
    )
    message = GmailMessage.objects.create(
        user=user,
        message_id=f"audit-message-{classifier}",
        thread_id=f"audit-thread-{classifier}",
        received_at=timezone.now(),
        subject="Private email subject that must not be exposed",
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        classifier=classifier,
        event_type=GmailEventType.APPLICATION_RECEIVED,
        confidence=91,
        model_name="gpt-test",
    )
    return ApplicationUpdateProposal.objects.create(
        user=user,
        message=message,
        analysis=analysis,
        application=application,
        proposal_type=ProposalType.UPDATE_APPLICATION,
        review_note="Private reviewer note that must not be exposed",
    )


@pytest.mark.django_db
@override_settings(AI_AUDIT_URL=AUDIT_KEY)
def test_staff_can_access_the_hidden_openapi_schema(client):
    client.force_login(_staff_user())

    response = client.get(reverse("ai_audit:openapi_schema", kwargs={"audit_key": AUDIT_KEY}))

    assert response.status_code == 200
    assert response["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert response["Referrer-Policy"] == "same-origin"
    payload = response.json()
    assert payload["openapi"] == "3.0.3"
    assert "/api/ai-proposals/" in payload["paths"]


@pytest.mark.django_db
@override_settings(AI_AUDIT_URL=AUDIT_KEY)
def test_audit_api_is_hidden_from_non_staff_and_wrong_urls(client):
    user = get_user_model().objects.create_user("audit-user", email="audit-user@example.com")
    client.force_login(user)

    response = client.get(reverse("ai_audit:swagger", kwargs={"audit_key": AUDIT_KEY}))
    wrong_url = client.get(reverse("ai_audit:swagger", kwargs={"audit_key": "wrong-audit-key"}))

    assert response.status_code == 404
    assert wrong_url.status_code == 404


@pytest.mark.django_db
@override_settings(AI_AUDIT_URL="")
def test_audit_api_is_disabled_until_a_secret_url_is_configured(client):
    client.force_login(_staff_user())

    response = client.get(reverse("ai_audit:swagger", kwargs={"audit_key": AUDIT_KEY}))

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(AI_AUDIT_URL=AUDIT_KEY)
def test_navigation_shows_the_audit_link_only_to_staff(client):
    staff = _staff_user()
    regular_user = get_user_model().objects.create_user(
        "regular-user",
        email="regular@example.com",
    )
    audit_url = reverse("ai_audit:swagger", kwargs={"audit_key": AUDIT_KEY})

    client.force_login(staff)
    staff_response = client.get(reverse("dashboard"))
    client.force_login(regular_user)
    regular_response = client.get(reverse("dashboard"))

    assert audit_url.encode() in staff_response.content
    assert audit_url.encode() not in regular_response.content


@pytest.mark.django_db
@override_settings(AI_AUDIT_URL=AUDIT_KEY)
def test_audit_api_returns_only_redacted_ai_proposal_metadata(client):
    staff = _staff_user()
    ai_proposal = _ai_proposal(user=staff)
    _ai_proposal(user=staff, classifier=AnalysisClassifier.RULE)
    client.force_login(staff)

    response = client.get(reverse("ai_audit:ai_proposals", kwargs={"audit_key": AUDIT_KEY}))

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["results"][0]["proposal_id"] == ai_proposal.pk
    assert payload["results"][0]["application"]["id"] == ai_proposal.application_id
    assert "subject" not in response.content.decode()
    assert "Private reviewer note" not in response.content.decode()


@pytest.mark.django_db
@override_settings(AI_AUDIT_URL=AUDIT_KEY)
def test_audit_api_lists_all_applications_including_records_without_ai_history(client):
    staff = _staff_user()
    ai_proposal = _ai_proposal(user=staff)
    manual_application = JobApplication.objects.create(
        user=staff,
        company="Manual GmbH",
        title="Manual application",
        notes="Private note that must not be exposed",
    )
    client.force_login(staff)

    response = client.get(reverse("ai_audit:applications", kwargs={"audit_key": AUDIT_KEY}))

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert {item["id"] for item in payload["results"]} == {
        ai_proposal.application_id,
        manual_application.pk,
    }
    assert "Private note" not in response.content.decode()


@pytest.mark.django_db
@override_settings(AI_AUDIT_URL=AUDIT_KEY)
def test_audit_api_lists_only_applications_with_pending_proposals(client):
    staff = _staff_user()
    pending = _ai_proposal(user=staff)
    unrelated = JobApplication.objects.create(user=staff, company="Manual GmbH", title="Manual application")
    client.force_login(staff)

    response = client.get(reverse("ai_audit:pending_applications", kwargs={"audit_key": AUDIT_KEY}))

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["results"][0]["id"] == pending.application_id
    assert payload["results"][0]["pending_proposals"] == [
        {
            "proposal_id": pending.pk,
            "proposal_type": ProposalType.UPDATE_APPLICATION,
            "matching": {"score": 0, "method": None},
            "analysis": {
                "event_type": GmailEventType.APPLICATION_RECEIVED,
                "classifier": AnalysisClassifier.AI,
                "confidence": 91,
                "analyzed_at": pending.analysis.analyzed_at.isoformat(),
            },
        }
    ]
    assert unrelated.pk not in {item["id"] for item in payload["results"]}


@pytest.mark.django_db
@override_settings(AI_AUDIT_URL=AUDIT_KEY)
def test_audit_api_explains_analysis_without_a_proposal(client):
    staff = _staff_user()
    message = GmailMessage.objects.create(
        user=staff,
        message_id="audit-no-proposal",
        thread_id="audit-no-proposal-thread",
        received_at=timezone.now(),
        subject="Private message subject that must not be exposed",
    )
    GmailAnalysis.objects.create(
        user=staff,
        message=message,
        classifier=AnalysisClassifier.RULE,
        event_type=GmailEventType.NOISE,
        is_job_related=False,
        confidence=99,
    )
    client.force_login(staff)

    response = client.get(reverse("ai_audit:gmail_analyses", kwargs={"audit_key": AUDIT_KEY}))

    assert response.status_code == 200
    payload = response.json()["results"][0]
    assert payload["gmail_message_id"] == "audit-no-proposal"
    assert payload["proposal_created"] is False
    assert payload["proposal_ids"] == []
    assert payload["reason"] == "not_job_related"
    assert "Private message subject" not in response.content.decode()
