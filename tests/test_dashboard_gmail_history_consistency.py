from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.applications.models import JobApplication
from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailEventType,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_stats.models import GmailDirection, GmailMessage


@pytest.mark.django_db
def test_dashboard_action_history_uses_assistant_action_semantics(client, monkeypatch):
    monkeypatch.setattr(
        "apps.accounts.dashboard.get_drive_status",
        lambda user: {"connected": False, "has_refresh_token": False},
    )
    user = get_user_model().objects.create_user(username="dashboard-history", password="test-pass")
    application = JobApplication.objects.create(
        user=user,
        title="im Bereich Softwareentwicklung",
        company="Klengel",
        status="applied",
    )
    received_at = timezone.now() - timedelta(days=2)
    message = GmailMessage.objects.create(
        user=user,
        message_id="dashboard-klengel-sent",
        thread_id="dashboard-klengel-thread",
        direction=GmailDirection.OUTBOUND,
        received_at=received_at,
        from_email="owner@example.com",
        to_emails=["info@klengel.de"],
        subject="Bewerbung im Bereich Softwareentwicklung",
        application=application,
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        event_type=GmailEventType.APPLICATION_SENT,
        is_job_related=True,
        confidence=95,
        extracted_data={
            "sent_kind": "direct_application",
            "company": "Klengel",
            "position_title": "im Bereich Softwareentwicklung",
        },
    )
    proposal = ApplicationUpdateProposal.objects.create(
        user=user,
        message=message,
        analysis=analysis,
        application=application,
        proposal_type=ProposalType.CREATE_APPLICATION,
        status=ProposalStatus.ACCEPTED,
        changes={
            "application": {
                "operation": "create",
                "title": "im Bereich Softwareentwicklung",
                "company": "Klengel",
            }
        },
        reviewed_at=timezone.now(),
    )

    client.force_login(user)
    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Create application" in content
    assert "Application sent" not in content
    assert "Accepted ·" not in content
    assert received_at.strftime("%d.%m.%Y %H:%M") in content
    assert reverse("gmail_assistant:gmail_proposal_detail", args=[proposal.pk]) in content


@pytest.mark.django_db
def test_dashboard_action_history_orders_by_gmail_message_time(client, monkeypatch):
    monkeypatch.setattr(
        "apps.accounts.dashboard.get_drive_status",
        lambda user: {"connected": False, "has_refresh_token": False},
    )
    user = get_user_model().objects.create_user(username="dashboard-history-order", password="test-pass")
    now = timezone.now()

    def create_history_item(*, suffix: str, subject: str, received_at, reviewed_at):
        message = GmailMessage.objects.create(
            user=user,
            message_id=f"dashboard-{suffix}",
            thread_id=f"dashboard-thread-{suffix}",
            direction=GmailDirection.INBOUND,
            received_at=received_at,
            from_email="hr@example.com",
            to_emails=["owner@example.com"],
            subject=subject,
        )
        analysis = GmailAnalysis.objects.create(
            user=user,
            message=message,
            event_type=GmailEventType.GENERAL_UPDATE,
            is_job_related=True,
            confidence=90,
            extracted_data={},
        )
        return ApplicationUpdateProposal.objects.create(
            user=user,
            message=message,
            analysis=analysis,
            proposal_type=ProposalType.UPDATE_APPLICATION,
            status=ProposalStatus.ACCEPTED,
            changes={},
            reviewed_at=reviewed_at,
        )

    create_history_item(
        suffix="older-message",
        subject="Older Gmail message",
        received_at=now - timedelta(days=2),
        reviewed_at=now,
    )
    create_history_item(
        suffix="newer-message",
        subject="Newer Gmail message",
        received_at=now - timedelta(days=1),
        reviewed_at=now - timedelta(days=3),
    )

    client.force_login(user)
    response = client.get(reverse("dashboard"))
    content = response.content.decode()

    assert content.index("Newer Gmail message") < content.index("Older Gmail message")
