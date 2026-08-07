from __future__ import annotations

from dataclasses import dataclass

from apps.applications.models import JobApplication
from apps.gmail_assistant.models import (
    AnalysisClassifier,
    ApplicationUpdateProposal,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_assistant.services.apply_proposal import ProposalApplyError, apply_proposal


BULK_CREATE_MIN_CONFIDENCE = 75


@dataclass(frozen=True)
class BulkCreateResult:
    created: int
    skipped_as_possible_duplicate: int
    failed: int


def eligible_bulk_create_proposals(*, user):
    """Return AI-backed, unlinked create proposals suitable for explicit batch review."""
    candidates = (
        ApplicationUpdateProposal.objects.filter(
            user=user,
            status=ProposalStatus.PENDING,
            proposal_type=ProposalType.CREATE_APPLICATION,
            application__isnull=True,
            analysis__classifier__in=(AnalysisClassifier.AI, AnalysisClassifier.RULE_AI),
            analysis__confidence__gte=BULK_CREATE_MIN_CONFIDENCE,
        )
        .select_related("analysis", "message")
        .order_by("message__received_at", "pk")
    )
    return [
        proposal
        for proposal in candidates
        if _has_valid_create_changes(proposal)
    ]


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
    return BulkCreateResult(created, skipped_as_possible_duplicate, failed)


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
