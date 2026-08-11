from __future__ import annotations

from collections.abc import Iterable

from apps.gmail_assistant.models import AnalysisClassifier, GmailEventType, ProposalType
from apps.gmail_assistant.services.apply_proposal import ProposalApplyError, apply_proposal


AUTO_APPLY_MIN_CONFIDENCE = 95
_SAFE_EVENT_TYPES = frozenset({GmailEventType.GENERAL_UPDATE, GmailEventType.SCREENING})
_SAFE_MATCH_METHODS = frozenset(
    {"gmail_thread", "thread_id", "external_application_id", "exact_company_title"}
)
_SAFE_APPLICATION_CHANGE_FIELDS = frozenset({"status", "recruiter_reply_at"})


def can_auto_apply(proposal) -> bool:
    """Return whether a proposal is safe enough for explicit user opt-in automation."""
    application_changes = proposal.changes.get("application") if isinstance(proposal.changes, dict) else None
    return bool(
        proposal.proposal_type == ProposalType.UPDATE_APPLICATION
        and proposal.application_id
        and proposal.analysis.classifier in {AnalysisClassifier.AI, AnalysisClassifier.RULE_AI}
        and proposal.analysis.confidence >= AUTO_APPLY_MIN_CONFIDENCE
        and proposal.analysis.event_type in _SAFE_EVENT_TYPES
        and proposal.match_method in _SAFE_MATCH_METHODS
        and isinstance(application_changes, dict)
        and application_changes
        and set(application_changes) <= _SAFE_APPLICATION_CHANGE_FIELDS
    )


def auto_apply_trusted_proposals(*, proposals: Iterable, user) -> int:
    """Atomically apply only proposals that meet every conservative safeguard."""
    applied = 0
    for proposal in proposals:
        if not can_auto_apply(proposal):
            continue
        try:
            result = apply_proposal(
                proposal=proposal,
                user=user,
                review_note=(
                    f"Automatically accepted: AI confidence {proposal.analysis.confidence}% "
                    f"with verified {proposal.match_method} match."
                ),
            )
        except ProposalApplyError:
            continue
        applied += int(not result.already_accepted)
    return applied
