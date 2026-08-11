from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.gmail_assistant.models import (
    AnalysisClassifier,
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailEventType,
    ProposalType,
)
from apps.gmail_stats.models import GmailMessage


AUDIT_KEY = "gmail-audit-test-key"


def _staff_user(username: str = "gmail-audit-staff"):
    return get_user_model().objects.create_user(
        username,
        email=f"{username}@example.com",
        is_staff=True,
    )


def _create_proposal(*, user, confidence: int, classifier: str = AnalysisClassifier.AI):
    message = GmailMessage.objects.create(
        user=user,
        message_id=f"high-confidence-{user.pk}-{confidence}-{classifier}",
        thread_id=f"thread-{user.pk}-{confidence}-{classifier}",
        received_at=timezone.now(),
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        classifier=classifier,
        event_type=GmailEventType.APPLICATION_RECEIVED,
        confidence=confidence,
    )
    return ApplicationUpdateProposal.objects.create(
        user=user,
        message=message,
        analysis=analysis,
        proposal_type=ProposalType.CREATE_APPLICATION,
        changes={
            "application": {
                "operation": "create",
                "title": "Python Developer",
                "company": "Example GmbH",
                "location": "Chemnitz",
                "source": "other",
                "status": "applied",
                "applied_at": message.received_at.isoformat(),
            }
        },
    )


@pytest.mark.django_db
@override_settings(AI_AUDIT_URL=AUDIT_KEY)
def test_high_confidence_audit_endpoint_matches_bulk_create_eligibility(client):
    staff = _staff_user()
    eligible = _create_proposal(user=staff, confidence=80)
    _create_proposal(user=staff, confidence=74)
    _create_proposal(user=staff, confidence=99, classifier=AnalysisClassifier.RULE)
    client.force_login(staff)

    response = client.get(
        reverse("ai_audit:high_confidence_applications", kwargs={"audit_key": AUDIT_KEY})
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["min_confidence"] == 75
    assert payload["results"][0]["proposal_id"] == eligible.pk
    assert payload["results"][0]["proposed_application"]["company"] == "Example GmbH"


@pytest.mark.django_db
@override_settings(AI_AUDIT_URL=AUDIT_KEY)
def test_high_confidence_audit_endpoint_can_filter_by_user(client):
    staff = _staff_user()
    other = _staff_user("gmail-audit-other")
    own = _create_proposal(user=staff, confidence=90)
    _create_proposal(user=other, confidence=90)
    client.force_login(staff)

    response = client.get(
        reverse("ai_audit:high_confidence_applications", kwargs={"audit_key": AUDIT_KEY}),
        {"user_id": staff.pk},
    )

    payload = response.json()
    assert payload["count"] == 1
    assert payload["results"][0]["proposal_id"] == own.pk


@pytest.mark.django_db
@override_settings(AI_AUDIT_URL=AUDIT_KEY)
def test_gmail_audit_schema_uses_neutral_name_and_lists_high_confidence_endpoint(client):
    staff = _staff_user()
    client.force_login(staff)

    response = client.get(reverse("ai_audit:openapi_schema", kwargs={"audit_key": AUDIT_KEY}))

    assert response.status_code == 200
    payload = response.json()
    assert payload["info"]["title"] == "JobApply Gmail audit API"
    assert "/api/high-confidence-applications/" in payload["paths"]
