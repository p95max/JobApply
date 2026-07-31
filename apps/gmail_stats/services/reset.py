from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.gmail_stats.models import GmailAssistantSettings, GmailMessage, GmailSyncState


def reset_gmail_assistant_data(*, user: Any) -> dict[str, int]:
    """Delete only one user's cached Gmail Assistant data.

    Job applications, Google credentials, and the user's AI consent are kept.
    Gmail analyses and proposals are removed by the message foreign-key cascades.
    """
    with transaction.atomic():
        messages = GmailMessage.objects.filter(user=user)
        message_count = messages.count()
        messages.delete()
        sync_state_count, _ = GmailSyncState.objects.filter(user=user).delete()
        GmailAssistantSettings.objects.filter(user=user).update(
            last_successful_run_at=None,
            last_error_at=None,
            last_error_message="",
        )
    return {"messages": message_count, "sync_states": sync_state_count}
