from __future__ import annotations

from html import escape

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.gmail_assistant.models import ApplicationUpdateProposal, GmailEventType
from apps.telegram_bot.notifications import send_notification_once, url_keyboard


def _jobapply_url(path: str) -> str:
    domain = str(getattr(settings, "DJANGO_SITE_DOMAIN", "jobapply.p95max.dev")).strip().strip("/")
    if domain.startswith(("http://", "https://")):
        base_url = domain
    else:
        base_url = f"https://{domain}"
    return f"{base_url}{path}"


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
        icon = "❌"
        delivery_type = "gmail_rejection"
    else:
        title = "Interview invitation"
        icon = "📅"
        delivery_type = "gmail_interview_invitation"

    text = (
        f"{icon} <b>{escape(title)}</b>\n\n"
        f"🏢 Company: <b>{escape(company)}</b>\n"
        f"💼 Position: <b>{escape(position)}</b>\n\n"
        "🔎 Review the pending proposal in JobApply."
    )
    event_key = f"{delivery_type}:{instance.message.message_id}"
    assistant_url = _jobapply_url("/gmail_stats/gmail/assistant/")

    transaction.on_commit(
        lambda: send_notification_once(
            event_key=event_key,
            event_type=delivery_type,
            text=text,
            reply_markup=url_keyboard("📨 Open Gmail Assistant", assistant_url),
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
