from __future__ import annotations

import pytest
from django.utils import timezone

from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailEventType,
    ProposalType,
)
from apps.gmail_stats.models import GmailMessage


@pytest.mark.django_db
def test_rejection_notification_is_sent_after_commit(
    django_user_model,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    user = django_user_model.objects.create_user("owner", email="owner@example.com")
    message = GmailMessage.objects.create(
        user=user,
        message_id="gmail-1",
        thread_id="thread-1",
        received_at=timezone.now(),
        subject="Absage",
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        event_type=GmailEventType.REJECTION,
        is_job_related=True,
        extracted_data={"company": "Example GmbH", "position_title": "Developer"},
    )
    calls = []
    monkeypatch.setattr(
        "apps.gmail_assistant.signals.send_notification_once",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    with django_capture_on_commit_callbacks(execute=True):
        ApplicationUpdateProposal.objects.create(
            user=user,
            message=message,
            analysis=analysis,
            proposal_type=ProposalType.UPDATE_APPLICATION,
            changes={"application": {"status": {"old": "applied", "new": "rejected"}}},
        )

    assert len(calls) == 1
    assert calls[0]["event_key"] == "gmail_rejection:gmail-1"
    assert calls[0]["event_type"] == "gmail_rejection"
    assert "Example GmbH" in calls[0]["text"]


@pytest.mark.django_db
def test_interview_notification_is_sent_once_for_new_proposal(
    django_user_model,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    user = django_user_model.objects.create_user("owner", email="owner@example.com")
    message = GmailMessage.objects.create(
        user=user,
        message_id="gmail-2",
        thread_id="thread-2",
        received_at=timezone.now(),
        subject="Interview",
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        event_type=GmailEventType.INTERVIEW_INVITATION,
        is_job_related=True,
        extracted_data={"company": "Example GmbH", "position_title": "Developer"},
    )
    calls = []
    monkeypatch.setattr(
        "apps.gmail_assistant.signals.send_notification_once",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    with django_capture_on_commit_callbacks(execute=True):
        proposal = ApplicationUpdateProposal.objects.create(
            user=user,
            message=message,
            analysis=analysis,
            proposal_type=ProposalType.CREATE_INTERVIEW,
            changes={"interview": {"operation": "create"}},
        )
        proposal.save(update_fields=["updated_at"])

    assert len(calls) == 1
    assert calls[0]["event_key"] == "gmail_interview_invitation:gmail-2"
    assert calls[0]["event_type"] == "gmail_interview_invitation"


@pytest.mark.django_db
def test_regular_proposal_does_not_send_notification(
    django_user_model,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    user = django_user_model.objects.create_user("owner", email="owner@example.com")
    message = GmailMessage.objects.create(
        user=user,
        message_id="gmail-3",
        thread_id="thread-3",
        received_at=timezone.now(),
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        event_type=GmailEventType.GENERAL_UPDATE,
        is_job_related=True,
    )
    calls = []
    monkeypatch.setattr(
        "apps.gmail_assistant.signals.send_notification_once",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    with django_capture_on_commit_callbacks(execute=True):
        ApplicationUpdateProposal.objects.create(
            user=user,
            message=message,
            analysis=analysis,
            proposal_type=ProposalType.UPDATE_APPLICATION,
        )

    assert calls == []
