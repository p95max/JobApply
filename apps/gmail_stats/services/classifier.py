from __future__ import annotations

import re
from dataclasses import dataclass

from apps.gmail_stats.models import GmailEventType


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


_JOB_CONTEXT_TERMS = (
    "bewerbung",
    "application",
    "position",
    "stelle",
    "vacancy",
    "job opportunity",
    "kandidatur",
)

_LEGACY_TYPE_BY_EVENT = {
    GmailEventType.APPLICATION_RECEIVED: "auto_ack",
    GmailEventType.INTERVIEW_INVITATION: "invite",
    GmailEventType.INTERVIEW_RESCHEDULED: "invite",
    GmailEventType.INTERVIEW_CANCELLED: "invite",
    GmailEventType.REJECTION: "rejection",
    GmailEventType.NOISE: "noise",
    GmailEventType.UNKNOWN: "unknown",
}


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
    context = _matching_terms(content, _JOB_CONTEXT_TERMS)

    noise = _matching_terms(content, ("newsletter", "job alert", "unsubscribe", "marketing", "rabatt"))
    if noise:
        return _result(GmailEventType.NOISE, 90, noise, False)

    withdrawal = _matching_terms(
        content,
        (
            "withdrawal confirmed",
            "application withdrawal confirmed",
            "application withdrawn",
            "bewerbung zurückgezogen",
        ),
    )
    if withdrawal:
        return _result(GmailEventType.WITHDRAWAL_CONFIRMATION, 95, withdrawal)

    rejection = _matching_terms(
        content,
        (
            "absage",
            "nicht berücksichtigen",
            "haben uns für andere kandidaten entschieden",
            "unfortunately",
            "we regret",
            "other candidates",
            "cannot offer you",
        ),
    )
    if context and rejection:
        return _result(GmailEventType.REJECTION, 92, context + rejection)

    offer = _matching_terms(content, ("job offer", "offer for the position", "angebot für die position"))
    if offer:
        return _result(GmailEventType.OFFER, 94, offer)

    cancellation = _matching_terms(
        content,
        (
            "interview cancelled",
            "interview canceled",
            "gespräch wurde abgesagt",
            "gespräch abgesagt",
            "termin abgesagt",
        ),
    )
    if cancellation:
        return _result(GmailEventType.INTERVIEW_CANCELLED, 94, cancellation)

    reschedule = _matching_terms(
        content,
        ("interview rescheduled", "reschedule the interview", "termin verschieben", "gespräch verschieben"),
    )
    if reschedule:
        return _result(GmailEventType.INTERVIEW_RESCHEDULED, 94, reschedule)

    invitation = _matching_terms(
        content,
        (
            "interview invitation",
            "invite you to an interview",
            "einladung zum vorstellungsgespräch",
            "einladung zu einem gespräch",
            "interview termin",
        ),
    )
    if invitation:
        return _result(GmailEventType.INTERVIEW_INVITATION, 92, invitation)

    screening = _matching_terms(content, ("phone screen", "telefoninterview", "initial screening"))
    if screening:
        return _result(GmailEventType.SCREENING, 88, screening)

    documents = _matching_terms(
        content,
        ("please send your documents", "documents requested", "bitte senden sie ihre unterlagen", "lebenslauf nachreichen"),
    )
    if documents:
        return _result(GmailEventType.DOCUMENTS_REQUESTED, 88, documents)

    confirmation_required = _matching_terms(
        content,
        (
            "confirm your application",
            "confirm your email",
            "bewerbung bestätigen",
            "bestätigen sie ihre bewerbung",
            "e-mail adresse bestätigen",
        ),
    )
    if confirmation_required:
        return _result(GmailEventType.APPLICATION_CONFIRMATION_REQUIRED, 90, confirmation_required)

    application_sent = _matching_terms(
        content,
        (
            "application submitted",
            "application has been submitted",
            "application sent",
            "bewerbung wurde versendet",
        ),
    )
    if application_sent:
        return _result(GmailEventType.APPLICATION_SENT, 88, application_sent)

    received = _matching_terms(
        content,
        (
            "we received your application",
            "application has been received",
            "eingangsbestätigung",
            "haben ihre bewerbung erhalten",
        ),
    )
    if received:
        return _result(GmailEventType.APPLICATION_RECEIVED, 86, received)

    update = _matching_terms(
        content,
        (
            "update on your application",
            "rückmeldung zu ihrer bewerbung",
            "we will get back to you",
            "bewerbung wird geprüft",
        ),
    )
    if context and update:
        return _result(GmailEventType.GENERAL_UPDATE, 75, context + update)

    if context:
        return _result(GmailEventType.GENERAL_UPDATE, 65, context)
    return _result(GmailEventType.UNKNOWN, 0, (), False)


def classify(subject: str, snippet: str) -> Classified:
    """Return the legacy statistics category for existing Gmail dashboard callers."""
    result = classify_event(subject, snippet)
    return Classified(result.detected_type, result.confidence)
