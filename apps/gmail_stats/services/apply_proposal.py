from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.applications.models import ApplicationStatus, JobApplication
from apps.gmail_stats.models import ApplicationUpdateProposal, ProposalStatus, ProposalType
from apps.gmail_stats.services.status_policy import proposed_status, status_reference_at

_APPLICATION_FIELDS = {"title", "company", "location", "source", "status", "applied_at", "recruiter_reply_at"}
_INTERVIEW_FIELDS = {"starts_at", "location", "notes", "status"}


class ProposalApplyError(Exception):
    """Raised when a proposal cannot be safely applied."""


@dataclass(frozen=True)
class ApplyProposalResult:
    """The outcome of an ownership-safe proposal apply operation."""

    proposal: ApplicationUpdateProposal
    application: JobApplication | None
    interview: Any | None
    already_accepted: bool


def apply_proposal(
    *,
    proposal: ApplicationUpdateProposal,
    user: Any,
    overrides: dict[str, Any] | None = None,
) -> ApplyProposalResult:
    """Atomically apply a pending proposal owned by the current user."""
    overrides = overrides or {}
    with transaction.atomic():
        locked = (
            ApplicationUpdateProposal.objects.select_for_update()
            .select_related("message", "analysis")
            .filter(pk=proposal.pk, user=user)
            .first()
        )
        if locked is None:
            raise ProposalApplyError("proposal not found")
        if locked.status == ProposalStatus.ACCEPTED:
            return ApplyProposalResult(locked, locked.application, None, True)
        if locked.status != ProposalStatus.PENDING:
            raise ProposalApplyError("proposal is no longer pending")
        if locked.message.user_id != user.pk or locked.analysis.user_id != user.pk:
            raise ProposalApplyError("proposal relations do not belong to the current user")

        application = _apply_application(locked, user, overrides)
        interview = _apply_interview(locked, user, application, overrides)
        if application:
            locked.message.application = application
            locked.message.save(update_fields=["application", "updated_at"])
        locked.status = ProposalStatus.ACCEPTED
        locked.reviewed_at = timezone.now()
        locked.save(update_fields=["status", "reviewed_at", "updated_at"])
        return ApplyProposalResult(locked, application, interview, False)


def review_proposal(*, proposal: ApplicationUpdateProposal, user: Any, status: str) -> ApplicationUpdateProposal:
    """Mark a pending proposal rejected or ignored after an ownership check."""
    if status not in {ProposalStatus.REJECTED, ProposalStatus.IGNORED}:
        raise ValueError("review status must be rejected or ignored")
    with transaction.atomic():
        locked = ApplicationUpdateProposal.objects.select_for_update().filter(pk=proposal.pk, user=user).first()
        if locked is None:
            raise ProposalApplyError("proposal not found")
        if locked.status != ProposalStatus.PENDING:
            raise ProposalApplyError("proposal is no longer pending")
        locked.status = status
        locked.reviewed_at = timezone.now()
        locked.save(update_fields=["status", "reviewed_at", "updated_at"])
        return locked


def _apply_application(proposal: ApplicationUpdateProposal, user: Any, overrides: dict[str, Any]) -> JobApplication | None:
    changes = _merged_changes(proposal.changes.get("application"), overrides.get("application"), _APPLICATION_FIELDS)
    if proposal.proposal_type == ProposalType.CREATE_APPLICATION:
        if not changes or changes.get("operation") != "create":
            raise ProposalApplyError("create proposal has invalid application changes")
        application = JobApplication(
            user=user,
            title=_required_string(changes, "title", 200),
            company=_required_string(changes, "company", 200),
            location=_optional_string(changes.get("location"), 200) or "",
            source=_optional_string(changes.get("source"), 50) or "other",
            status=_optional_string(changes.get("status"), 20) or ApplicationStatus.APPLIED,
            applied_at=_datetime_value(changes.get("applied_at"), "applied_at"),
        )
        _validate_status(application.status)
        application.full_clean()
        application.save()
        return application

    application = proposal.application
    if application is None:
        if proposal.proposal_type == ProposalType.UPDATE_APPLICATION:
            raise ProposalApplyError("assign an application before accepting this proposal")
        return None
    if application.user_id != user.pk:
        raise ProposalApplyError("application does not belong to the proposal user")
    application = JobApplication.objects.select_for_update().get(pk=application.pk, user=user)
    if not changes:
        return application

    status_change = changes.get("status")
    if isinstance(status_change, dict):
        new_status = status_change.get("new")
        expected = proposed_status(
            event_type=proposal.analysis.event_type,
            current_status=application.status,
            message_received_at=proposal.message.received_at,
            application_updated_at=status_reference_at(application),
        )
        if new_status != expected:
            raise ProposalApplyError("status transition is no longer allowed")
        application.status = new_status
    for field in _APPLICATION_FIELDS - {"status"}:
        if field not in changes:
            continue
        value = changes[field]
        if isinstance(value, dict):
            value = value.get("new")
        if field in {"applied_at", "recruiter_reply_at"}:
            value = _datetime_value(value, field, allow_none=field == "recruiter_reply_at")
        elif field in {"title", "company"}:
            value = _required_string({field: value}, field, 200)
        else:
            value = _optional_string(value, 200) or ""
        setattr(application, field, value)
    application.full_clean()
    application.save()
    return application


def _apply_interview(
    proposal: ApplicationUpdateProposal,
    user: Any,
    application: JobApplication | None,
    overrides: dict[str, Any],
) -> Any | None:
    changes = _merged_changes(proposal.changes.get("interview"), overrides.get("interview"), _INTERVIEW_FIELDS)
    if not changes:
        return None
    if application is None or application.user_id != user.pk:
        raise ProposalApplyError("interview proposal requires an owned application")

    from apps.interviews.models import InterviewEvent, InterviewStatus

    operation = changes.get("operation")
    if operation == "create":
        starts_at = _datetime_value(changes.get("starts_at"), "starts_at")
        interview, _ = InterviewEvent.objects.get_or_create(
            user=user,
            application=application,
            starts_at=starts_at,
            defaults={
                "location": _optional_string(changes.get("location"), 255) or "",
                "notes": _optional_string(changes.get("notes"), 1000) or "",
            },
        )
        return interview
    if operation != "update":
        raise ProposalApplyError("interview operation is invalid")
    interview_id = changes.get("interview_id")
    interview = InterviewEvent.objects.select_for_update().filter(
        pk=interview_id,
        user=user,
        application=application,
    ).first()
    if interview is None:
        raise ProposalApplyError("interview not found")
    for field in _INTERVIEW_FIELDS:
        if field not in changes:
            continue
        value = changes[field]
        if field == "starts_at":
            value = _datetime_value(value, field)
        elif field == "status":
            if value not in InterviewStatus.values:
                raise ProposalApplyError("interview status is invalid")
        else:
            value = _optional_string(value, 1000 if field == "notes" else 255) or ""
        setattr(interview, field, value)
    interview.full_clean()
    interview.save()
    return interview


def _merged_changes(base: Any, override: Any, allowed_fields: set[str]) -> dict[str, Any]:
    if base is None:
        return {}
    if not isinstance(base, dict) or (override is not None and not isinstance(override, dict)):
        raise ProposalApplyError("proposal changes are invalid")
    result = dict(base)
    for field, value in (override or {}).items():
        if field not in allowed_fields:
            raise ProposalApplyError(f"field {field} cannot be overridden")
        result[field] = value
    return result


def _datetime_value(value: Any, field: str, allow_none: bool = False) -> datetime | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not (parsed := parse_datetime(value)) or timezone.is_naive(parsed):
        raise ProposalApplyError(f"{field} must be a timezone-aware ISO-8601 datetime")
    return parsed


def _required_string(values: dict[str, Any], field: str, max_length: int) -> str:
    value = _optional_string(values.get(field), max_length)
    if value is None:
        raise ProposalApplyError(f"{field} is required")
    return value


def _optional_string(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > max_length:
        raise ProposalApplyError("string value is invalid")
    return value.strip() or None


def _validate_status(value: str) -> None:
    if value not in ApplicationStatus.values:
        raise ProposalApplyError("application status is invalid")
