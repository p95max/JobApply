from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from apps.applications.models import JobApplication
from apps.gmail_assistant.models import (
    AnalysisClassifier,
    ApplicationUpdateProposal,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_assistant.services.application_matcher import match_for_message
from apps.gmail_assistant.services.apply_proposal import ProposalApplyError, apply_proposal


BULK_CREATE_MIN_CONFIDENCE = 75
_EXACT_REMATCH_METHODS = frozenset(
    {"gmail_thread", "thread_id", "external_application_id", "exact_company_title", "company_temporal"}
)


@dataclass(frozen=True)
class BulkCreateResult:
    created: int
    skipped_as_possible_duplicate: int
    failed: int
    linked_for_review: int


def eligible_bulk_create_proposals(*, user=None):
    """Return unlinked high-confidence create proposals suitable for explicit batch review.

    ``user`` is optional so the staff-only audit API can expose the same
    eligibility logic across users without duplicating filters. Normal product
    flows always pass the current user explicitly.
    """
    candidates = ApplicationUpdateProposal.objects.filter(
        status=ProposalStatus.PENDING,
        proposal_type=ProposalType.CREATE_APPLICATION,
        application__isnull=True,
        analysis__classifier__in=(AnalysisClassifier.AI, AnalysisClassifier.RULE_AI),
        analysis__confidence__gte=BULK_CREATE_MIN_CONFIDENCE,
    )
    if user is not None:
        candidates = candidates.filter(user=user)
    candidates = candidates.select_related("analysis", "message").order_by("message__received_at", "pk")
    return [proposal for proposal in candidates if _has_valid_create_changes(proposal)]


def bulk_create_eligible_proposals(*, user) -> BulkCreateResult:
    """Create only explicitly allowed AI proposals, retaining uncertain items for manual review."""
    created = skipped_as_possible_duplicate = failed = 0
    for proposal in eligible_bulk_create_proposals(user=user):
        if _matches_existing_application(proposal=proposal, user=user):
            skipped_as_possible_duplicate += 1
            continue
        try:
            result = apply_proposal(
                proposal=proposal,
                user=user,
                review_note=(
                    "Bulk-created after explicit user confirmation "
                    f"(AI confidence: {proposal.analysis.confidence}%)."
                ),
            )
        except ProposalApplyError:
            failed += 1
            continue
        if result.already_accepted:
            failed += 1
        else:
            created += 1
    linked_for_review = rematch_pending_proposals(user=user)
    return BulkCreateResult(created, skipped_as_possible_duplicate, failed, linked_for_review)


def rematch_pending_proposals(*, user) -> int:
    """Link only unambiguous exact matches; proposals always remain pending for review."""
    pending = (
        ApplicationUpdateProposal.objects.filter(
            user=user,
            status=ProposalStatus.PENDING,
            application__isnull=True,
        )
        .select_related("message", "analysis")
        .order_by("message_id", "pk")
    )
    rematched_message_ids: set[int] = set()
    linked = 0
    for proposal in pending:
        if proposal.message_id in rematched_message_ids:
            continue
        rematched_message_ids.add(proposal.message_id)
        match = match_for_message(
            user=user,
            message=proposal.message,
            extracted_data=proposal.analysis.extracted_data,
            event_type=proposal.analysis.event_type,
        )
        candidate = match.suggested
        if (
            candidate is None
            or candidate.application is None
            or candidate.method not in _EXACT_REMATCH_METHODS
        ):
            continue
        now = timezone.now()
        linked += ApplicationUpdateProposal.objects.filter(
            user=user,
            message_id=proposal.message_id,
            analysis_id=proposal.analysis_id,
            status=ProposalStatus.PENDING,
            application__isnull=True,
        ).update(
            application=candidate.application,
            match_score=candidate.score,
            match_method=candidate.method,
            updated_at=now,
        )
        if proposal.message.application_id is None:
            proposal.message.application = candidate.application
            proposal.message.save(update_fields=["application", "updated_at"])
    return linked


def _has_valid_create_changes(proposal: ApplicationUpdateProposal) -> bool:
    application = proposal.changes.get("application")
    if not isinstance(application, dict) or application.get("operation") != "create":
        return False
    return all(
        isinstance(application.get(field), str) and application[field].strip()
        for field in ("title", "company")
    )


def _matches_existing_application(*, proposal: ApplicationUpdateProposal, user) -> bool:
    application = proposal.changes["application"]
    return JobApplication.objects.filter(
        user=user,
        title__iexact=application["title"].strip(),
        company__iexact=application["company"].strip(),
    ).exists()
