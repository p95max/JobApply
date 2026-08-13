from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from apps.gmail_assistant.models import GmailEventType


@dataclass(frozen=True)
class Classified:
    detected_type: str
    confidence: int


@dataclass(frozen=True)
class RuleClassification:
    event_type: str
    detected_type: str
    is_job_related: bool
    confidence: int
    evidence: tuple[str, ...]


_PHRASES_PATH = Path(__file__).with_name("classifier_phrases.json")

_LEGACY_TYPE_BY_EVENT = {
    GmailEventType.APPLICATION_RECEIVED: "auto_ack",
    GmailEventType.INTERVIEW_INVITATION: "invite",
    GmailEventType.INTERVIEW_RESCHEDULED: "invite",
    GmailEventType.INTERVIEW_CANCELLED: "invite",
    GmailEventType.REJECTION: "rejection",
    GmailEventType.NOISE: "noise",
    GmailEventType.UNKNOWN: "unknown",
}


@lru_cache(maxsize=1)
def _phrases() -> dict[str, tuple[str, ...]]:
    """Load editable German and English classifier phrases from JSON."""
    with _PHRASES_PATH.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict) or not all(
        isinstance(group, str) and isinstance(terms, list) and all(isinstance(term, str) for term in terms)
        for group, terms in value.items()
    ):
        raise ValueError("classifier_phrases.json must map phrase groups to lists of strings")
    return {group: tuple(term.casefold() for term in terms) for group, terms in value.items()}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().casefold())


def _matching_terms(text: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(term for term in terms if term in text)


def _result(
    event_type: str,
    confidence: int,
    evidence: tuple[str, ...],
    is_job_related: bool = True,
) -> RuleClassification:
    detected_type = _LEGACY_TYPE_BY_EVENT.get(event_type, "response" if is_job_related else "unknown")
    return RuleClassification(event_type, detected_type, is_job_related, confidence, evidence)


def classify_event(subject: str, snippet: str, text: str = "") -> RuleClassification:
    """Classify a Gmail message with deterministic, explainable job-email rules."""
    content = _normalize(" ".join((subject or "", snippet or "", text or "")))
    phrases = _phrases()
    context = _matching_terms(content, phrases["job_context"])

    noise = _matching_terms(content, phrases["noise"])
    if noise:
        return _result(GmailEventType.NOISE, 90, noise, False)

    withdrawal = _matching_terms(content, phrases["withdrawal"])
    if withdrawal:
        return _result(GmailEventType.WITHDRAWAL_CONFIRMATION, 95, withdrawal)

    rejection = _matching_terms(content, phrases["rejection"])
    if context and rejection:
        return _result(GmailEventType.REJECTION, 92, context + rejection)

    offer = _matching_terms(content, phrases["offer"])
    if offer:
        return _result(GmailEventType.OFFER, 94, offer)

    cancellation = _matching_terms(content, phrases["interview_cancelled"])
    if cancellation:
        return _result(GmailEventType.INTERVIEW_CANCELLED, 94, cancellation)

    reschedule = _matching_terms(content, phrases["interview_rescheduled"])
    if reschedule:
        return _result(GmailEventType.INTERVIEW_RESCHEDULED, 94, reschedule)

    invitation = _matching_terms(content, phrases["interview_invitation"])
    if invitation:
        return _result(GmailEventType.INTERVIEW_INVITATION, 92, invitation)

    screening = _matching_terms(content, phrases["screening"])
    if screening:
        return _result(GmailEventType.SCREENING, 88, screening)

    documents = _matching_terms(content, phrases["documents_requested"])
    if documents:
        return _result(GmailEventType.DOCUMENTS_REQUESTED, 88, documents)

    draft_reminder = _matching_terms(content, phrases["application_draft_reminder"])
    if context and draft_reminder:
        return _result(GmailEventType.APPLICATION_DRAFT_REMINDER, 94, context + draft_reminder)

    confirmation_required = _matching_terms(content, phrases["application_confirmation_required"])
    if confirmation_required:
        return _result(GmailEventType.APPLICATION_CONFIRMATION_REQUIRED, 90, confirmation_required)

    application_sent = _matching_terms(content, phrases["application_sent"])
    if application_sent:
        return _result(GmailEventType.APPLICATION_SENT, 88, application_sent)

    received = _matching_terms(content, phrases["application_received"])
    if received:
        return _result(GmailEventType.APPLICATION_RECEIVED, 86, received)

    update = _matching_terms(content, phrases["general_update"])
    if context and update:
        return _result(GmailEventType.GENERAL_UPDATE, 75, context + update)

    if context:
        return _result(GmailEventType.GENERAL_UPDATE, 65, context)
    return _result(GmailEventType.UNKNOWN, 0, (), False)


def classify(subject: str, snippet: str) -> Classified:
    """Return the legacy statistics category for existing Gmail dashboard callers."""
    result = classify_event(subject, snippet)
    return Classified(result.detected_type, result.confidence)
