from __future__ import annotations

import json
import logging
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from apps.gmail_assistant.services.application_matcher import normalize_company, normalize_position
from apps.gmail_assistant.services.company_resolution import resolve_extracted_company
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
    suggested = match.suggested
    application = suggested.application if suggested else None
    pending_create_proposal = suggested.pending_create_proposal if suggested else None
    match_score = suggested.score if suggested else 0
    match_method = suggested.method if suggested else ""
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
            [_candidate_label(candidate) for candidate in match.ambiguous],
        )

    if application is not None or analysis.event_type not in _CREATE_APPLICATION_EVENTS:
        ApplicationUpdateProposal.objects.filter(
            message=message,
            analysis=analysis,
            proposal_type=ProposalType.CREATE_APPLICATION,
            status=ProposalStatus.PENDING,
        ).delete()
    if analysis.event_type in {GmailEventType.NOISE, GmailEventType.UNKNOWN}:
        return _pending_results(proposals)

    if not action_required:
        ApplicationUpdateProposal.objects.filter(
            message=message,
            analysis=analysis,
            proposal_type=ProposalType.ACTION_REQUIRED,
            status=ProposalStatus.PENDING,
        ).delete()

    if application is None and analysis.event_type in _CREATE_APPLICATION_EVENTS:
        if pending_create_proposal is not None and _same_pending_application_intent(
            message=message,
            pending_create_proposal=pending_create_proposal,
            match_method=match_method,
        ):
            _record_related_message(proposal=pending_create_proposal, message=message)
            return []
        if not _can_create_application(extracted):
            platform_duplicate = _pending_platform_duplicate(message=message, extracted=extracted)
            if platform_duplicate is not None:
                _record_related_message(proposal=platform_duplicate, message=message)
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
            return _pending_results(proposals)

    if application is None:
        if pending_create_proposal is not None:
            pending_target = {"pending_create_proposal_id": pending_create_proposal.pk}
            application_changes = _pending_application_changes(
                message=message,
                analysis=analysis,
                pending_create_proposal=pending_create_proposal,
            )
            if application_changes:
                proposals.append(
                    _create_pending(
                        message=message,
                        analysis=analysis,
                        application=None,
                        proposal_type=ProposalType.UPDATE_APPLICATION,
                        match_score=match_score,
                        match_method=match_method,
                        changes={"application": application_changes, **pending_target},
                    )
                )
            if action_required:
                proposals.append(
                    _create_pending(
                        message=message,
                        analysis=analysis,
                        application=None,
                        proposal_type=ProposalType.ACTION_REQUIRED,
                        match_score=match_score,
                        match_method=match_method,
                        changes={"action": _action_changes(extracted), **pending_target},
                    )
                )
            if analysis.event_type == GmailEventType.INTERVIEW_INVITATION:
                interview_changes, proposal_type = _interview_changes(
                    event_type=analysis.event_type,
                    application=None,
                    extracted=extracted,
                )
                if interview_changes:
                    proposals.append(
                        _create_pending(
                            message=message,
                            analysis=analysis,
                            application=None,
                            proposal_type=proposal_type,
                            match_score=match_score,
                            match_method=match_method,
                            changes={"interview": interview_changes, **pending_target},
                        )
                    )
            return _pending_results(proposals)
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
        return _pending_results(proposals)

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
    return _pending_results(proposals)


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


def _pending_application_changes(
    *,
    message: Any,
    analysis: Any,
    pending_create_proposal: ApplicationUpdateProposal,
) -> dict[str, Any]:
    """Build a deferred status update for an application that is not persisted yet."""
    changes: dict[str, Any] = {}
    status = proposed_status(
        event_type=analysis.event_type,
        current_status="applied",
        message_received_at=message.received_at,
        application_updated_at=pending_create_proposal.message.received_at,
    )
    if status:
        changes["status"] = {"old": "applied", "new": status}
    if should_set_recruiter_reply_at(analysis.event_type):
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


def _pending_results(proposals: list[ApplicationUpdateProposal]) -> list[ApplicationUpdateProposal]:
    """Return only proposals that still need review."""
    return [proposal for proposal in proposals if proposal.status == ProposalStatus.PENDING]


def _create_pending(**kwargs: Any) -> ApplicationUpdateProposal:
    identity = {
        "user": kwargs["message"].user,
        "message": kwargs["message"],
        "analysis": kwargs["analysis"],
        "proposal_type": kwargs["proposal_type"],
    }
    reviewed = (
        ApplicationUpdateProposal.objects.filter(**identity)
        .exclude(status=ProposalStatus.PENDING)
        .order_by("-reviewed_at", "-pk")
        .first()
    )
    if reviewed is not None:
        ApplicationUpdateProposal.objects.filter(**identity, status=ProposalStatus.PENDING).delete()
        return reviewed

    proposal, created = ApplicationUpdateProposal.objects.get_or_create(
        **identity,
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
    normalized = normalize_company(company)
    return any(
        normalized == platform or normalized.startswith(f"{platform} ")
        for platform in (normalize_company(value) for value in _rules()["job_platform_companies"])
    )


def _pending_platform_duplicate(*, message: Any, extracted: dict[str, Any]) -> ApplicationUpdateProposal | None:
    """Attach a platform acknowledgement to its real employer proposal when unambiguous.

    A platform may repeat the same submission email a few seconds later.  It is
    useful review evidence, but must never create a second application whose
    company is the platform itself.
    """
    company = _string_or_none(extracted.get("company"))
    title = normalize_position(extracted.get("position_title"))
    if not company or not title or not _is_job_platform(company):
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
    matches: list[ApplicationUpdateProposal] = []
    for candidate in candidates:
        proposed = candidate.changes.get("application")
        if not isinstance(proposed, dict) or _is_job_platform(str(proposed.get("company") or "")):
            continue
        if normalize_position(proposed.get("title")) != title:
            continue
        if abs(candidate.message.received_at - message.received_at) <= timedelta(minutes=5):
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


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


def _same_pending_application_intent(
    *,
    message: Any,
    pending_create_proposal: ApplicationUpdateProposal,
    match_method: str,
) -> bool:
    """Return whether a matched pending create is an acknowledgement, not a new application.

    Two applications to the same company and role on different dates are valid
    separate records.  Only an identical Gmail thread or a near-simultaneous
    duplicate acknowledgement may be collapsed into one pending create.
    """
    if match_method == "pending_create_gmail_thread":
        return True
    return abs(pending_create_proposal.message.received_at - message.received_at) <= timedelta(minutes=5)


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


def _candidate_label(candidate: Any) -> int:
    """Return an ID suitable for structured logs without assuming a real application."""
    if candidate.application is not None:
        return candidate.application.pk
    if candidate.pending_create_proposal is not None:
        return candidate.pending_create_proposal.pk
    return 0


def rebuild_pending_proposals_for_user(*, user: Any) -> int:
    """Rebuild pending proposal links oldest-first after a Gmail sync.

    Gmail returns message IDs in no useful order.  This second, local pass makes
    initial application messages available as temporary targets before later
    replies (rejection, interview, required action) are rebuilt.
    """
    from apps.gmail_assistant.services.application_matcher import match_for_message
    from apps.gmail_assistant.models import GmailAnalysis

    rebuilt = 0
    analyses = (
        GmailAnalysis.objects.filter(user=user)
        .select_related("message")
        .order_by("message__received_at", "message__pk")
    )
    for analysis in analyses:
        resolved_data = resolve_extracted_company(analysis.extracted_data)
        if resolved_data != analysis.extracted_data:
            analysis.extracted_data = resolved_data
            analysis.save(update_fields=["extracted_data"])
        match = match_for_message(
            user=user,
            message=analysis.message,
            extracted_data=resolved_data,
            event_type=analysis.event_type,
        )
        rebuilt += len(build_proposals(message=analysis.message, analysis=analysis, match=match))
    return rebuilt
