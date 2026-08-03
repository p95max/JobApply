from __future__ import annotations

from django.http import HttpRequest

from apps.gmail_assistant.models import ApplicationUpdateProposal, ProposalStatus


def gmail_assistant_notifications(request: HttpRequest) -> dict[str, int]:
    """Expose the authenticated user's pending Gmail Assistant proposal count."""
    if not request.user.is_authenticated:
        return {"gmail_assistant_pending_count": 0}

    count = ApplicationUpdateProposal.objects.filter(
        user=request.user,
        status=ProposalStatus.PENDING,
    ).count()
    return {"gmail_assistant_pending_count": count}
