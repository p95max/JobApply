from __future__ import annotations

from datetime import datetime, timezone

import pytest
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.gmail_assistant.models import GmailAnalysis, GmailEventType
from apps.gmail_stats.models import GmailDirection, GmailMessage, GmailProcessingStatus
from apps.gmail_stats.services.direction import determine_direction, parse_recipients, parse_sender
from apps.gmail_assistant.services.sync import sync_gmail_messages_for_user


class FakeGmailClient:
    def __init__(self, *, profile_email: str, messages: dict[str, dict | Exception]):
        self.profile_email = profile_email
        self.messages = messages

    def list_message_ids(self, query: str, max_results: int = 500) -> list[str]:
        return list(self.messages)

    def get_profile_email(self) -> str:
        return self.profile_email

    def get_message_minimal(self, message_id: str) -> dict:
        result = self.messages[message_id]
        if isinstance(result, Exception):
            raise result
        return result

    def get_message_full(self, message_id: str) -> dict:
        return self.get_message_minimal(message_id)


def gmail_message(*, sender: str, recipients: str = "user@example.com") -> dict:
    return {
        "id": "gmail-id",
        "threadId": "thread-id",
        "internalDate": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
        "snippet": "Your application has been received.",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Application update"},
                {"name": "From", "value": sender},
                {"name": "To", "value": recipients},
            ]
        },
    }


@pytest.mark.parametrize(
    ("from_email", "recipients", "expected"),
    [
        ("recruiter@example.org", ["user@example.com"], GmailDirection.INBOUND),
        ("USER@example.com", ["recruiter@example.org"], GmailDirection.OUTBOUND),
        ("recruiter@example.org", ["other@example.org"], GmailDirection.UNKNOWN),
    ],
)
def test_determine_direction(from_email, recipients, expected):
    assert (
        determine_direction(
            from_email=from_email,
            recipient_emails=recipients,
            profile_email="user@example.com",
        )
        == expected
    )


def test_address_parsing_handles_display_names_and_malformed_headers():
    assert parse_sender("Recruiter Name <recruiter@example.org>") == (
        "Recruiter Name",
        "recruiter@example.org",
    )
    assert parse_sender("not an address") == ("", "")
    assert parse_recipients(["User <user@example.com>", "other@example.org, user@example.com"]) == [
        "user@example.com",
        "other@example.org",
    ]


@pytest.mark.django_db
def test_same_gmail_message_id_is_isolated_per_user(django_user_model):
    first_user = django_user_model.objects.create_user("first", email="first@example.com")
    second_user = django_user_model.objects.create_user("second", email="second@example.com")
    raw = gmail_message(sender="Recruiter <recruiter@example.org>", recipients="first@example.com")

    sync_gmail_messages_for_user(
        user=first_user,
        gmail_client=FakeGmailClient(profile_email="first@example.com", messages={"same-id": raw}),
    )
    raw["payload"]["headers"][2]["value"] = "second@example.com"
    sync_gmail_messages_for_user(
        user=second_user,
        gmail_client=FakeGmailClient(profile_email="second@example.com", messages={"same-id": raw}),
    )

    assert GmailMessage.objects.filter(message_id="same-id").count() == 2
    assert GmailMessage.objects.filter(user=first_user, message_id="same-id").count() == 1
    assert GmailMessage.objects.filter(user=second_user, message_id="same-id").count() == 1


@pytest.mark.django_db
def test_repeat_sync_does_not_create_duplicates(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    client = FakeGmailClient(
        profile_email="user@example.com",
        messages={"gmail-id": gmail_message(sender="recruiter@example.org")},
    )

    first = sync_gmail_messages_for_user(user=user, gmail_client=client)
    second = sync_gmail_messages_for_user(user=user, gmail_client=client)

    assert first["created"] == 1
    assert second["created"] == 0
    assert GmailMessage.objects.filter(user=user, message_id="gmail-id").count() == 1


@pytest.mark.django_db
def test_message_failure_does_not_abort_other_messages(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    client = FakeGmailClient(
        profile_email="user@example.com",
        messages={
            "bad-id": RuntimeError("Gmail API get failed"),
            "good-id": gmail_message(sender="recruiter@example.org"),
        },
    )

    result = sync_gmail_messages_for_user(user=user, gmail_client=client)

    assert result["failed"] == 1
    assert GmailMessage.objects.get(user=user, message_id="bad-id").processing_status == GmailProcessingStatus.FAILED
    assert GmailMessage.objects.get(user=user, message_id="good-id").processing_status == GmailProcessingStatus.ANALYZED


@pytest.mark.django_db
def test_outbound_messages_are_excluded_from_statistics(client, django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    UserProfile.objects.create(user=user, google_data_access_consent=True)
    outbound = GmailMessage.objects.create(
        user=user,
        message_id="outbound",
        thread_id="outbound-thread",
        direction=GmailDirection.OUTBOUND,
        received_at=datetime.now(timezone.utc),
        detected_type=GmailMessage.TYPE_RESPONSE,
    )
    inbound = GmailMessage.objects.create(
        user=user,
        message_id="inbound",
        thread_id="inbound-thread",
        direction=GmailDirection.INBOUND,
        received_at=datetime.now(timezone.utc),
        detected_type=GmailMessage.TYPE_RESPONSE,
    )
    GmailAnalysis.objects.create(
        user=user,
        message=outbound,
        event_type=GmailEventType.GENERAL_UPDATE,
        is_job_related=True,
    )
    GmailAnalysis.objects.create(
        user=user,
        message=inbound,
        event_type=GmailEventType.GENERAL_UPDATE,
        is_job_related=True,
    )

    client.force_login(user)
    response = client.get(reverse("gmail_stats:gmail_stats_api"))

    assert response.status_code == 200
    assert response.json()["job_related_emails"] == 1
