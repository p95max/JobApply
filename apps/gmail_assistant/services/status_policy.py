from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils import timezone

from apps.applications.models import ApplicationStatus
from apps.gmail_assistant.models import GmailEventType


_EVENT_STATUS = {
    GmailEventType.GENERAL_UPDATE: ApplicationStatus.REPLIED,
    GmailEventType.SCREENING: ApplicationStatus.SCREEN,
    GmailEventType.INTERVIEW_INVITATION: ApplicationStatus.INTERVIEW,
    GmailEventType.OFFER: ApplicationStatus.OFFER,
    GmailEventType.REJECTION: ApplicationStatus.REJECTED,
    GmailEventType.WITHDRAWAL_CONFIRMATION: ApplicationStatus.ARCHIVED,
}

_STATUS_RANK = {
    ApplicationStatus.APPLIED: 10,
    ApplicationStatus.REPLIED: 20,
    ApplicationStatus.SCREEN: 30,
    ApplicationStatus.INTERVIEW: 40,
    ApplicationStatus.OFFER: 50,
    ApplicationStatus.REJECTED: 60,
    ApplicationStatus.ARCHIVED: 70,
}

_RECRUITER_REPLY_EVENTS = {
    GmailEventType.GENERAL_UPDATE,
    GmailEventType.SCREENING,
    GmailEventType.INTERVIEW_INVITATION,
    GmailEventType.INTERVIEW_RESCHEDULED,
    GmailEventType.INTERVIEW_CANCELLED,
    GmailEventType.OFFER,
    GmailEventType.REJECTION,
}


def is_stale_message(message_received_at: datetime | None, application_updated_at: datetime | None) -> bool:
    """Return whether an email predates the application's latest known state."""
    if not message_received_at or not application_updated_at:
        return False
    if not timezone.is_aware(message_received_at) or not timezone.is_aware(application_updated_at):
        return False
    return message_received_at <= application_updated_at


def status_reference_at(application: Any) -> datetime | None:
    """Return the timestamp that represents the current application status.

    An application still in ``applied`` state has no recruiter-driven state
    transition yet, so its real application date is more reliable than an ORM
    ``updated_at`` timestamp produced while importing historical Gmail data.
    """
    if application.status == ApplicationStatus.APPLIED and application.applied_at:
        return application.applied_at
    return application.updated_at


def proposed_status(
    *,
    event_type: str,
    current_status: str,
    message_received_at: datetime | None = None,
    application_updated_at: datetime | None = None,
) -> str | None:
    """Return a non-downgrading status proposal, or None when no change is safe."""
    candidate = _EVENT_STATUS.get(event_type)
    if not candidate or is_stale_message(message_received_at, application_updated_at):
        return None

    current_rank = _STATUS_RANK.get(current_status)
    candidate_rank = _STATUS_RANK[candidate]
    if current_rank is None or candidate_rank <= current_rank:
        return None
    return candidate


def should_set_recruiter_reply_at(event_type: str) -> bool:
    """Return whether an event is a substantive recruiter response."""
    return event_type in _RECRUITER_REPLY_EVENTS
