from __future__ import annotations

from typing import Any

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


def build_proposals(*, message: Any, analysis: Any, match: Any) -> list[ApplicationUpdateProposal]:
    """Create deduplicated pending proposals without applying any application changes."""
    if message.user_id != analysis.user_id:
        raise ValueError("message and analysis must belong to the same user")
    if analysis.event_type in {GmailEventType.NOISE, GmailEventType.UNKNOWN}:
        return []

    application = match.suggested.application if match.suggested else None
    match_score = match.suggested.score if match.suggested else 0
    match_method = match.suggested.method if match.suggested else ""
    extracted = analysis.extracted_data
    proposals: list[ApplicationUpdateProposal] = []

    if application is None and analysis.event_type in _CREATE_APPLICATION_EVENTS and _can_create_application(extracted):
        proposal = _create_pending(
            message=message,
            analysis=analysis,
            application=None,
            proposal_type=ProposalType.CREATE_APPLICATION,
            match_score=0,
            match_method="unmatched",
            changes={"application": _create_application_changes(message, extracted)},
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

    if analysis.event_type in _ACTION_EVENTS:
        proposals.append(
            _create_pending(
                message=message,
                analysis=analysis,
                application=application,
                proposal_type=ProposalType.ACTION_REQUIRED,
                match_score=match_score,
                match_method=match_method,
                changes={
                    "action": {
                        "required": True,
                        "text": _string_or_none(extracted.get("action_text")),
                        "deadline_at": _string_or_none(extracted.get("deadline_at")),
                    }
                },
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
        proposal.changes = kwargs["changes"]
        proposal.match_score = kwargs["match_score"]
        proposal.match_method = kwargs["match_method"]
        proposal.save(update_fields=["changes", "match_score", "match_method", "updated_at"])
    return proposal


def _can_create_application(extracted: dict[str, Any]) -> bool:
    return bool(_string_or_none(extracted.get("company")) and _string_or_none(extracted.get("position_title")))


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
