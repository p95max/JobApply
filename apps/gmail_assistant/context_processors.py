from __future__ import annotations

from django.http import HttpRequest

from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailAssistantSettings,
    ProposalStatus,
)
from apps.reports.models import CloudBackupSettings


def gmail_assistant_notifications(request: HttpRequest) -> dict[str, int | bool]:
    """Expose authenticated user service status and pending proposal count."""
    if not request.user.is_authenticated:
        return {
            "gmail_assistant_pending_count": 0,
            "gmail_assistant_enabled": False,
            "cloud_backups_enabled": False,
        }

    count = ApplicationUpdateProposal.objects.filter(
        user=request.user,
        status=ProposalStatus.PENDING,
    ).count()
    assistant_enabled = GmailAssistantSettings.objects.filter(
        user=request.user,
        ai_enabled=True,
    ).exists()
    backups_enabled = CloudBackupSettings.objects.filter(
        user=request.user,
        enabled=True,
    ).exists()

    return {
        "gmail_assistant_pending_count": count,
        "gmail_assistant_enabled": assistant_enabled,
        "cloud_backups_enabled": backups_enabled,
    }
