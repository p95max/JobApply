from __future__ import annotations

from html import escape

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.gmail_assistant.models import ApplicationUpdateProposal, GmailEventType
from apps.telegram_bot.notifications import send_notification_once


@receiver(post_save, sender=ApplicationUpdateProposal)
def notify_significant_gmail_proposal(
    sender,
    instance: ApplicationUpdateProposal,
    created: bool,
    **kwargs,
) -> None:
    if not created:
        return

    event_type = instance.analysis.event_type
    if event_type not in {GmailEventType.REJECTION, GmailEventType.INTERVIEW_INVITATION}:
        return

    company, position = _proposal_identity(instance)
    if event_type == GmailEventType.REJECTION:
        title = "Application rejected"
        delivery_type = "gmail_rejection"
    else:
        title = "Interview invitation"
        delivery_type = "gmail_interview_invitation"

    text = (
        f"<b>{escape(title)}</b>\n"
        f"{escape(company)} — {escape(position)}\n"
        "Review the pending proposal in JobApply."
    )
    event_key = f"{delivery_type}:{instance.message_id}"

    transaction.on_commit(
        lambda: send_notification_once(
            event_key=event_key,
            event_type=delivery_type,
            text=text,
        )
    )


def _proposal_identity(proposal: ApplicationUpdateProposal) -> tuple[str, str]:
    if proposal.application_id and proposal.application:
        return proposal.application.company or "Unknown", proposal.application.title or "Unknown"

    extracted = proposal.analysis.extracted_data if proposal.analysis_id else {}
    changes = proposal.changes.get("application", {}) if isinstance(proposal.changes, dict) else {}
    company = extracted.get("company") or changes.get("company") or "Unknown"
    position = extracted.get("position_title") or changes.get("title") or "Unknown"
    return str(company), str(position)
