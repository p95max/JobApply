from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailEventType,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_stats.models import GmailDirection, GmailMessage


def _accepted_activity(*, user, index: int, subject: str | None = None) -> None:
    message = GmailMessage.objects.create(
        user=user,
        message_id=f"history-message-{index}",
        thread_id=f"history-thread-{index}",
        direction=GmailDirection.INBOUND,
        received_at=timezone.now(),
        from_email=f"recruiter{index}@example.com",
        to_emails=[user.email or "owner@example.com"],
        subject=subject or f"Application history {index}",
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        event_type=GmailEventType.GENERAL_UPDATE,
        is_job_related=True,
        confidence=90,
        extracted_data={},
    )
    ApplicationUpdateProposal.objects.create(
        user=user,
        message=message,
        analysis=analysis,
        proposal_type=ProposalType.ACTIVITY,
        status=ProposalStatus.ACCEPTED,
        changes={"activity": {"kind": "test"}},
        reviewed_at=timezone.now(),
    )


@pytest.mark.django_db
def test_action_history_uses_twenty_events_per_page(client):
    user = get_user_model().objects.create_user(
        username="history-pagination",
        email="owner@example.com",
        password="test-pass",
    )
    for index in range(21):
        _accepted_activity(user=user, index=index)

    client.force_login(user)
    response = client.get(
        reverse("gmail_assistant:gmail_assistant"),
        {"status": ProposalStatus.ACCEPTED},
    )

    assert response.status_code == 200
    assert len(response.context["proposal_groups"]) == 20
    assert response.context["paginator"].per_page == 20
    assert response.context["paginator"].num_pages == 2


@pytest.mark.django_db
def test_action_history_search_filters_before_pagination_and_preserves_query(client):
    user = get_user_model().objects.create_user(
        username="history-search",
        email="owner@example.com",
        password="test-pass",
    )
    for index in range(21):
        _accepted_activity(user=user, index=index)
    _accepted_activity(user=user, index=99, subject="Unique Klengel history event")

    client.force_login(user)
    response = client.get(
        reverse("gmail_assistant:gmail_assistant"),
        {"status": ProposalStatus.ACCEPTED, "q": "Klengel"},
    )

    assert response.status_code == 200
    assert response.context["history_search"] == "Klengel"
    assert len(response.context["proposal_groups"]) == 1
    assert response.context["proposal_groups"][0]["message"].subject == "Unique Klengel history event"
    assert response.context["paginator"].count == 1
    assert "q=Klengel" in response.context["base_qs"]
    content = response.content.decode()
    assert "Search Action history" in content
    assert 'value="Klengel"' in content
