from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.applications.models import ApplicationStatus
from apps.gmail_assistant.models import GmailEventType
from apps.gmail_assistant.services.classifier import classify, classify_event
from apps.gmail_assistant.services.status_policy import proposed_status, should_set_recruiter_reply_at
from tests.gmail_assistant_corpus import GMAIL_ASSISTANT_FIXTURES


@pytest.mark.parametrize(
    ("text", "event_type"),
    [
        ("Bitte bestätigen Sie Ihre Bewerbung.", GmailEventType.APPLICATION_CONFIRMATION_REQUIRED),
        ("Your application has been submitted.", GmailEventType.APPLICATION_SENT),
        ("Wir haben Ihre Bewerbung erhalten.", GmailEventType.APPLICATION_RECEIVED),
        ("Rückmeldung zu Ihrer Bewerbung: Wir melden uns bald.", GmailEventType.GENERAL_UPDATE),
        ("We would like to arrange a phone screen for your application.", GmailEventType.SCREENING),
        ("Bitte senden Sie Ihre Unterlagen nach.", GmailEventType.DOCUMENTS_REQUESTED),
        ("Einladung zum Vorstellungsgespräch für Ihre Bewerbung.", GmailEventType.INTERVIEW_INVITATION),
        ("Wir möchten den Termin verschieben.", GmailEventType.INTERVIEW_RESCHEDULED),
        ("Das Gespräch wurde abgesagt.", GmailEventType.INTERVIEW_CANCELLED),
        ("We are pleased to make you a job offer.", GmailEventType.OFFER),
        ("Leider können wir Ihre Bewerbung nicht berücksichtigen.", GmailEventType.REJECTION),
        ("Your application withdrawal confirmed.", GmailEventType.WITHDRAWAL_CONFIRMATION),
        ("Newsletter: Rabatt auf Kurse", GmailEventType.NOISE),
        ("Your receipt is ready.", GmailEventType.UNKNOWN),
    ],
)
def test_classify_event_types(text, event_type):
    result = classify_event(text, "")

    assert result.event_type == event_type
    assert result.evidence or event_type == GmailEventType.UNKNOWN


@pytest.mark.parametrize("text", ["Leider regnet es heute.", "Teams meeting tomorrow.", "Termin beim Zahnarzt."])
def test_classifier_does_not_treat_broad_words_as_job_events(text):
    assert classify_event(text, "").event_type == GmailEventType.UNKNOWN


def test_legacy_classifier_keeps_dashboard_categories():
    assert classify("Interview invitation", "for your application").detected_type == "invite"
    assert classify("Application has been received", "thank you").detected_type == "auto_ack"


@pytest.mark.parametrize(
    "fixture",
    GMAIL_ASSISTANT_FIXTURES,
    ids=lambda fixture: fixture.name,
)
def test_classify_sanitized_fixture_corpus(fixture):
    result = classify_event(fixture.subject, fixture.text)

    assert result.event_type == fixture.event_type
    assert result.evidence or fixture.event_type == GmailEventType.UNKNOWN


def test_fixture_corpus_includes_an_outbound_duplicate_and_prompt_injection():
    assert any(fixture.direction == "outbound" for fixture in GMAIL_ASSISTANT_FIXTURES)
    assert sum(fixture.duplicate_group == "ats-receipt" for fixture in GMAIL_ASSISTANT_FIXTURES) == 2
    assert any(fixture.name == "prompt_injection" for fixture in GMAIL_ASSISTANT_FIXTURES)


@pytest.mark.parametrize(
    ("event_type", "current_status", "expected"),
    [
        (GmailEventType.GENERAL_UPDATE, ApplicationStatus.APPLIED, ApplicationStatus.REPLIED),
        (GmailEventType.INTERVIEW_INVITATION, ApplicationStatus.REPLIED, ApplicationStatus.INTERVIEW),
        (GmailEventType.GENERAL_UPDATE, ApplicationStatus.INTERVIEW, None),
        (GmailEventType.INTERVIEW_CANCELLED, ApplicationStatus.INTERVIEW, None),
        (GmailEventType.APPLICATION_RECEIVED, ApplicationStatus.APPLIED, None),
    ],
)
def test_status_policy_does_not_downgrade(event_type, current_status, expected):
    assert proposed_status(event_type=event_type, current_status=current_status) == expected


def test_status_policy_rejects_stale_email():
    now = timezone.now()
    assert (
        proposed_status(
            event_type=GmailEventType.INTERVIEW_INVITATION,
            current_status=ApplicationStatus.APPLIED,
            message_received_at=now - timedelta(days=1),
            application_updated_at=now,
        )
        is None
    )


def test_auto_ack_never_sets_recruiter_reply_time():
    assert should_set_recruiter_reply_at(GmailEventType.APPLICATION_RECEIVED) is False
    assert should_set_recruiter_reply_at(GmailEventType.GENERAL_UPDATE) is True
