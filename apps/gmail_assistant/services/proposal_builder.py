from __future__ import annotations

import json
import logging
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from apps.gmail_assistant.services.application_matcher import normalize_company, normalize_position
from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailEventType,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_assistant.services.status_policy import proposed_status, should_set_recruiter_reply_at, status_reference_at

_ACTION_EVENTS = {
    GmailEventType.APPLICATION_CONFIRMATION_REQUIRED,
    GmailEventType.DOCUMENTS_REQUESTED,
}
_CREATE_APPLICATION_EVENTS = {
    GmailEventType.APPLICATION_SENT,
    GmailEventType.APPLICATION_RECEIVED,
}
_INTERVIEW_EVENTS = {
    GmailEventType.INTERVIEW_INVITATION,
    GmailEventType.INTERVIEW_RESCHEDULED,
    GmailEventType.INTERVIEW_CANCELLED,
}
_MANUAL_ASSIGNMENT_EVENTS = {GmailEventType.REJECTION}
_RULES_PATH = Path(__file__).with_name("proposal_rules.json")
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _rules() -> dict[str, tuple[str, ...]]:
    """Load editable job-board rules without mixing them into code logic."""
    with _RULES_PATH.open(encoding="utf-8") as source:
        value = json.load(source)
    required_groups = {"optional_nudge_senders", "optional_nudge_phrases", "job_platform_companies"}
    if (
        not isinstance(value, dict)
        or set(value) != required_groups
        or not all(isinstance(terms, list) and all(isinstance(term, str) for term in terms) for terms in value.values())
    ):
        raise ValueError("proposal_rules.json must contain the expected lists of strings")
    return {group: tuple(term.casefold() for term in terms) for group, terms in value.items()}


def build_proposals(*, message: Any, analysis: Any, match: Any) -> list[ApplicationUpdateProposal]:
    """Create deduplicated pending proposals without applying any application changes."""
    if message.user_id != analysis.user_id:
        raise ValueError("message and analysis must belong to the same user")

    _normalize_known_event_type(message=message, analysis=analysis)
    application = match.suggested.application if match.suggested else None
    match_score = match.suggested.score if match.suggested else 0
    match_method = match.suggested.method if match.suggested else ""
    extracted = analysis.extracted_data
    action_required = _is_action_required(message=message, event_type=analysis.event_type, extracted=extracted)
    proposals: list[ApplicationUpdateProposal] = []

    if analysis.event_type == GmailEventType.REJECTION:
        logger.info(
            "gmail_rejection_match analysis_id=%s message_id=%s matched_application_id=%s method=%s score=%s ambiguous_candidates=%s",
            analysis.pk,
            message.message_id,
            application.pk if application else None,
            match_method or "unmatched",
            match_score,
            [candidate.application.pk for candidate in match.ambiguous],
        )

    if application is not None or analysis.event_type not in _CREATE_APPLICATION_EVENTS:
        ApplicationUpdateProposal.objects.filter(
            message=message,
            analysis=analysis,
            proposal_type=ProposalType.CREATE_APPLICATION,
            status=ProposalStatus.PENDING,
        ).delete()
    if analysis.event_type in {GmailEventType.NOISE, GmailEventType.UNKNOWN}:
        return proposals

    if not action_required:
        ApplicationUpdateProposal.objects.filter(
            message=message,
            analysis=analysis,
            proposal_type=ProposalType.ACTION_REQUIRED,
            status=ProposalStatus.PENDING,
        ).delete()

    if application is None and analysis.event_type in _CREATE_APPLICATION_EVENTS:
        if not _can_create_application(extracted):
            ApplicationUpdateProposal.objects.filter(
                message=message,
                analysis=analysis,
                proposal_type=ProposalType.CREATE_APPLICATION,
                status=ProposalStatus.PENDING,
            ).delete()
        else:
            changes = _create_application_changes(message, extracted)
            duplicate = _pending_create_duplicate(message=message, changes=changes)
            if duplicate is not None:
                _record_related_message(proposal=duplicate, message=message)
                return []
            proposal = _create_pending(
                message=message,
                analysis=analysis,
                application=None,
                proposal_type=ProposalType.CREATE_APPLICATION,
                match_score=0,
                match_method="unmatched",
                changes={"application": changes},
            )
            proposals.append(proposal)
            return proposals

    if application is None:
        if analysis.event_type in _MANUAL_ASSIGNMENT_EVENTS:
            proposals.append(
                _create_pending(
                    message=message,
                    analysis=analysis,
                    application=None,
                    proposal_type=ProposalType.UPDATE_APPLICATION,
                    match_score=0,
                    match_method="unmatched",
                    changes={
                        "application": {
                            "status": {"old": None, "new": "rejected"},
                            "recruiter_reply_at": {"old": None, "new": message.received_at.isoformat()},
                        }
                    },
                )
            )
        if action_required:
            proposals.append(
                _create_pending(
                    message=message,
                    analysis=analysis,
                    application=None,
                    proposal_type=ProposalType.ACTION_REQUIRED,
                    match_score=0,
                    match_method="unmatched",
                    changes={"action": _action_changes(extracted)},
                )
            )
        return proposals

    application_changes = _application_changes(message=message, analysis=analysis, application=application)
    if application_changes:
        proposals.append(
            _create_pending(
                message=message,
                analysis=analysis,
                application=application,
                proposal_type=ProposalType.UPDATE_APPLICATION,
                match_score=match_score,
                match_method=match_method,
                changes={"application": application_changes},
            )
        )

    if action_required:
        proposals.append(
            _create_pending(
                message=message,
                analysis=analysis,
                application=application,
                proposal_type=ProposalType.ACTION_REQUIRED,
                match_score=match_score,
                match_method=match_method,
                changes={"action": _action_changes(extracted)},
            )
        )

    if analysis.event_type in _INTERVIEW_EVENTS:
        interview_changes, proposal_type = _interview_changes(
            event_type=analysis.event_type,
            application=application,
            extracted=extracted,
        )
        if interview_changes:
            proposals.append(
                _create_pending(
                    message=message,
                    analysis=analysis,
                    application=application,
                    proposal_type=proposal_type,
                    match_score=match_score,
                    match_method=match_method,
                    changes={"interview": interview_changes},
                )
            )
    return proposals


def _normalize_known_event_type(*, message: Any, analysis: Any) -> None:
    sender = str(getattr(message, "from_email", "") or "").casefold()
    subject = str(getattr(message, "subject", "") or "").casefold()
    if (
        sender == "indeedapply@indeed.com"
        and subject.startswith("bewerbung über indeed:")
        and analysis.event_type == GmailEventType.APPLICATION_RECEIVED
    ):
        analysis.event_type = GmailEventType.APPLICATION_SENT
        analysis.save(update_fields=["event_type", "updated_at"])


def _is_action_required(*, message: Any, event_type: str, extracted: dict[str, Any]) -> bool:
    if event_type in _ACTION_EVENTS:
        return True
    if _is_optional_job_board_nudge(message=message, extracted=extracted):
        return False
    return extracted.get("action_required") is True and _string_or_none(extracted.get("action_text")) is not None


def _is_optional_job_board_nudge(*, message: Any, extracted: dict[str, Any]) -> bool:
    rules = _rules()
    sender = str(getattr(message, "from_email", "") or "").lower()
    sender_domain = sender.rsplit("@", 1)[-1] if "@" in sender else sender
    if sender_domain not in rules["optional_nudge_senders"]:
        return False
    combined = " ".join(
        str(value or "").lower()
        for value in (
            getattr(message, "subject", ""),
            extracted.get("summary"),
            extracted.get("action_text"),
        )
    )
    return any(phrase in combined for phrase in rules["optional_nudge_phrases"])


def _action_changes(extracted: dict[str, Any]) -> dict[str, Any]:
    return {
        "required": True,
        "text": _string_or_none(extracted.get("action_text")),
        "deadline_at": _string_or_none(extracted.get("deadline_at")),
    }


def _application_changes(*, message: Any, analysis: Any, application: Any) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    status = proposed_status(
        event_type=analysis.event_type,
        current_status=application.status,
        message_received_at=message.received_at,
        application_updated_at=status_reference_at(application),
    )
    if status:
        changes["status"] = {"old": application.status, "new": status}
    if application.recruiter_reply_at is None and should_set_recruiter_reply_at(analysis.event_type):
        changes["recruiter_reply_at"] = {"old": None, "new": message.received_at.isoformat()}
    return changes


def _interview_changes(*, event_type: str, application: Any, extracted: dict[str, Any]) -> tuple[dict[str, Any], str]:
    from apps.interviews.models import InterviewEvent, InterviewStatus

    interview = extracted.get("interview") if isinstance(extracted.get("interview"), dict) else {}
    starts_at = _string_or_none(interview.get("starts_at"))
    if event_type == GmailEventType.INTERVIEW_INVITATION:
        return (
            {
                "operation": "create",
                "starts_at": starts_at,
                "location": _string_or_none(interview.get("location")) or "",
                "notes": "Extracted from Gmail message",
            },
            ProposalType.CREATE_INTERVIEW,
        )

    existing = InterviewEvent.objects.filter(user=application.user, application=application).order_by("-starts_at").first()
    if not existing:
        return {}, ProposalType.UPDATE_INTERVIEW
    changes: dict[str, Any] = {"operation": "update", "interview_id": existing.pk}
    if event_type == GmailEventType.INTERVIEW_CANCELLED:
        changes["status"] = InterviewStatus.CANCELED
    elif starts_at:
        changes["starts_at"] = starts_at
        changes["location"] = _string_or_none(interview.get("location")) or existing.location
    else:
        return {}, ProposalType.UPDATE_INTERVIEW
    return changes, ProposalType.UPDATE_INTERVIEW


def _create_pending(**kwargs: Any) -> ApplicationUpdateProposal:
    proposal, created = ApplicationUpdateProposal.objects.get_or_create(
        user=kwargs["message"].user,
        message=kwargs["message"],
        analysis=kwargs["analysis"],
        proposal_type=kwargs["proposal_type"],
        status=ProposalStatus.PENDING,
        defaults={
            "application": kwargs["application"],
            "match_score": kwargs["match_score"],
            "match_method": kwargs["match_method"],
            "changes": kwargs["changes"],
        },
    )
    if not created:
        proposal.application = kwargs["application"]
        proposal.changes = kwargs["changes"]
        proposal.match_score = kwargs["match_score"]
        proposal.match_method = kwargs["match_method"]
        proposal.save(update_fields=["application", "changes", "match_score", "match_method", "updated_at"])
    return proposal


def _can_create_application(extracted: dict[str, Any]) -> bool:
    company = _string_or_none(extracted.get("company"))
    return bool(company and _string_or_none(extracted.get("position_title")) and not _is_job_platform(company))


def _is_job_platform(company: str) -> bool:
    return normalize_company(company) in {normalize_company(value) for value in _rules()["job_platform_companies"]}


def _pending_create_duplicate(*, message: Any, changes: dict[str, Any]) -> ApplicationUpdateProposal | None:
    """Return the same pending creation intent, without merging unrelated applications."""
    title = normalize_position(changes.get("title"))
    company = normalize_company(changes.get("company"))
    if not title or not company:
        return None
    candidates = (
        ApplicationUpdateProposal.objects.filter(
            user=message.user,
            proposal_type=ProposalType.CREATE_APPLICATION,
            status=ProposalStatus.PENDING,
        )
        .exclude(message=message)
        .select_related("message")
        .order_by("-created_at")[:100]
    )
    for candidate in candidates:
        proposed = candidate.changes.get("application")
        if not isinstance(proposed, dict):
            continue
        if normalize_position(proposed.get("title")) != title:
            continue
        if normalize_company(proposed.get("company")) != company:
            continue
        if abs(candidate.message.received_at - message.received_at) <= timedelta(minutes=5):
            return candidate
    return None


def _record_related_message(*, proposal: ApplicationUpdateProposal, message: Any) -> None:
    """Keep short review evidence when a second acknowledgement confirms one intent."""
    changes = dict(proposal.changes)
    related = changes.get("related_messages")
    related_messages = list(related) if isinstance(related, list) else []
    item = {
        "subject": str(message.subject or ""),
        "from_email": str(message.from_email or ""),
        "received_at": message.received_at.isoformat(),
    }
    if item not in related_messages:
        related_messages.append(item)
        changes["related_messages"] = related_messages
        proposal.changes = changes
        proposal.save(update_fields=["changes", "updated_at"])


def _create_application_changes(message: Any, extracted: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation": "create",
        "title": extracted["position_title"][:200],
        "company": extracted["company"][:200],
        "location": _string_or_none(extracted.get("location")) or "",
        "source": "other",
        "status": "applied",
        "applied_at": message.received_at.isoformat(),
    }


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
