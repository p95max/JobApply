from __future__ import annotations

from html import escape

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailAssistantSettings,
    GmailEventType,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_stats.models import GmailDirection
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


@receiver(post_save, sender=GmailAssistantSettings)
def record_proposal_less_sent_activity(
    sender,
    instance: GmailAssistantSettings,
    created: bool,
    update_fields,
    **kwargs,
) -> None:
    """Materialize processed direct Sent applications after a successful sync.

    The normal proposal builder remains authoritative. If an accepted create
    proposal lost its application because that application was deleted, restore
    a new pending create proposal for review. Otherwise create an accepted
    activity record only when no proposal exists at all.
    """
    if created or not instance.last_successful_run_at:
        return
    if update_fields is not None and "last_successful_run_at" not in update_fields:
        return

    analyses = (
        GmailAnalysis.objects.filter(
            user=instance.user,
            event_type=GmailEventType.APPLICATION_SENT,
            message__direction=GmailDirection.OUTBOUND,
            extracted_data__sent_kind="direct_application",
        )
        .select_related("message")
        .order_by("message__received_at")
    )
    for analysis in analyses:
        existing = ApplicationUpdateProposal.objects.filter(
            user=instance.user,
            message=analysis.message,
            analysis=analysis,
        )

        stale_accepted_create = (
            existing.filter(
                proposal_type=ProposalType.CREATE_APPLICATION,
                status=ProposalStatus.ACCEPTED,
                application__isnull=True,
            )
            .order_by("-reviewed_at", "-pk")
            .first()
        )
        has_pending_create = existing.filter(
            proposal_type=ProposalType.CREATE_APPLICATION,
            status=ProposalStatus.PENDING,
        ).exists()
        if stale_accepted_create is not None and not has_pending_create:
            application_changes = stale_accepted_create.changes.get("application")
            if isinstance(application_changes, dict) and application_changes.get("operation") == "create":
                ApplicationUpdateProposal.objects.create(
                    user=instance.user,
                    message=analysis.message,
                    analysis=analysis,
                    application=None,
                    proposal_type=ProposalType.CREATE_APPLICATION,
                    status=ProposalStatus.PENDING,
                    match_score=0,
                    match_method="recreated_after_application_deletion",
                    changes={"application": dict(application_changes)},
                    review_note="",
                )
                continue

        if existing.exclude(proposal_type=ProposalType.ACTIVITY).exists() or existing.filter(
            proposal_type=ProposalType.ACTIVITY
        ).exists():
            continue
        ApplicationUpdateProposal.objects.create(
            user=instance.user,
            message=analysis.message,
            analysis=analysis,
            application=analysis.message.application,
            proposal_type=ProposalType.ACTIVITY,
            status=ProposalStatus.ACCEPTED,
            match_score=100 if analysis.message.application_id else 0,
            match_method="processed_gmail_activity",
            changes={"activity": {"kind": "application_sent", "source": "gmail_sent"}},
            review_note="Recorded automatically after successful Gmail sync; no application change was required.",
            reviewed_at=timezone.now(),
        )


def _proposal_identity(proposal: ApplicationUpdateProposal) -> tuple[str, str]:
    if proposal.application_id and proposal.application:
        return proposal.application.company or "Unknown", proposal.application.title or "Unknown"

    extracted = proposal.analysis.extracted_data if proposal.analysis_id else {}
    changes = proposal.changes.get("application", {}) if isinstance(proposal.changes, dict) else {}
    company = extracted.get("company") or changes.get("company") or "Unknown"
    position = extracted.get("position_title") or changes.get("title") or "Unknown"
    return str(company), str(position)
