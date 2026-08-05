from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from apps.gmail_assistant.models import ApplicationUpdateProposal, ProposalStatus
from apps.gmail_assistant.services.apply_proposal import ProposalApplyError, apply_proposal, review_proposal


CALLBACK_PREFIX = "proposal"
ACCEPT_ACTION = "accept"
REJECT_ACTION = "reject"


@dataclass(frozen=True)
class ProposalActionResult:
    proposal: ApplicationUpdateProposal | None
    outcome: str
    message: str


def callback_data(proposal_id: int, action: str) -> str:
    if action not in {ACCEPT_ACTION, REJECT_ACTION}:
        raise ValueError("Unsupported proposal action")
    return f"{CALLBACK_PREFIX}:{proposal_id}:{action}"


def parse_callback_data(value: object) -> tuple[int, str] | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX or parts[2] not in {ACCEPT_ACTION, REJECT_ACTION}:
        return None
    try:
        proposal_id = int(parts[1])
    except ValueError:
        return None
    return (proposal_id, parts[2]) if proposal_id > 0 else None


def apply_callback_action(
    *,
    proposal_id: int,
    action: str,
    user,
    ttl_seconds: int,
) -> ProposalActionResult:
    proposal = ApplicationUpdateProposal.objects.filter(pk=proposal_id, user=user).first()
    if proposal is None:
        return ProposalActionResult(None, "not_found", "This proposal is no longer available.")
    if proposal.status != ProposalStatus.PENDING:
        return ProposalActionResult(proposal, "already_reviewed", "This proposal was already reviewed.")
    expires_at = proposal.created_at + timedelta(seconds=max(1, ttl_seconds))
    if timezone.now() > expires_at:
        return ProposalActionResult(proposal, "expired", "This action expired. Review the proposal in JobApply.")

    try:
        if action == ACCEPT_ACTION:
            apply_proposal(proposal=proposal, user=user, review_note="Accepted from Telegram")
            message = "Proposal accepted. The application was updated in JobApply."
        elif action == REJECT_ACTION:
            review_proposal(
                proposal=proposal,
                user=user,
                status=ProposalStatus.REJECTED,
                review_note="Rejected from Telegram",
            )
            message = "Proposal rejected. No application changes were made."
        else:
            return ProposalActionResult(proposal, "invalid", "This action is not available.")
    except ProposalApplyError:
        return ProposalActionResult(proposal, "stale", "This proposal changed. Review it in JobApply.")

    proposal.refresh_from_db()
    return ProposalActionResult(proposal, action, message)
