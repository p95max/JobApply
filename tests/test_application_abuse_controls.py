from __future__ import annotations

import json

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.applications.models import JobApplication
from apps.gmail_assistant.models import ApplicationUpdateProposal, GmailAnalysis, GmailEventType, ProposalType
from apps.gmail_assistant.services.apply_proposal import ProposalApplyError, apply_proposal
from apps.gmail_stats.models import GmailMessage


@pytest.mark.django_db
@override_settings(APPLICATION_BULK_DELETE_MAX_IDS=2)
def test_bulk_delete_rejects_excessive_selection(client, django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    applications = [
        JobApplication.objects.create(user=user, company=f"Company {index}", title="Developer")
        for index in range(3)
    ]
    client.force_login(user)

    response = client.post(
        reverse("applications:bulk_delete"),
        data=json.dumps({"ids": [application.pk for application in applications]}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert JobApplication.objects.filter(user=user).count() == 3


@pytest.mark.django_db
@override_settings(APPLICATIONS_PER_USER_LIMIT=1)
def test_manual_creation_respects_the_per_user_application_limit(client, django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    JobApplication.objects.create(user=user, company="Existing GmbH", title="Developer")
    client.force_login(user)

    response = client.post(
        reverse("applications:create"),
        {
            "company": "New GmbH",
            "title": "Python Developer",
            "source": "other",
            "status": "applied",
            "applied_at": "2026-08-10",
        },
    )

    assert response.status_code == 200
    assert b"Application limit reached" in response.content
    assert JobApplication.objects.filter(user=user).count() == 1


@pytest.mark.django_db
@override_settings(APPLICATIONS_PER_USER_LIMIT=1)
def test_gmail_proposal_cannot_bypass_the_per_user_application_limit(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    JobApplication.objects.create(user=user, company="Existing GmbH", title="Developer")
    message = GmailMessage.objects.create(
        user=user,
        message_id="application-limit-message",
        thread_id="application-limit-thread",
        received_at=timezone.now(),
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        event_type=GmailEventType.APPLICATION_RECEIVED,
    )
    proposal = ApplicationUpdateProposal.objects.create(
        user=user,
        message=message,
        analysis=analysis,
        proposal_type=ProposalType.CREATE_APPLICATION,
        changes={
            "application": {
                "operation": "create",
                "title": "New role",
                "company": "New GmbH",
                "applied_at": timezone.now().isoformat(),
            }
        },
    )

    with pytest.raises(ProposalApplyError, match="Application limit reached"):
        apply_proposal(proposal=proposal, user=user)

    assert JobApplication.objects.filter(user=user).count() == 1
