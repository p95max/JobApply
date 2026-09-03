from __future__ import annotations

from datetime import timedelta
from html import escape

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
from apps.site_urls import jobapply_url
from apps.telegram_bot.notifications import send_notification_once, url_keyboard


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
    assistant_url = jobapply_url("/gmail_stats/gmail/assistant/")

    transaction.on_commit(
        lambda: send_notification_once(
            event_key=event_key,
            event_type=delivery_type,
            text=text,
            reply_markup=url_keyboard("📨 Open Gmail Assistant", assistant_url),
        )
    )


def _activity_changes(proposal: ApplicationUpdateProposal) -> dict:
    changes = dict(proposal.changes) if isinstance(proposal.changes, dict) else {}
    changes["activity"] = {"kind": "application_sent", "source": "gmail_sent"}
    return changes


def _has_created_application(proposal: ApplicationUpdateProposal) -> bool:
    application_changes = proposal.changes.get("application") if isinstance(proposal.changes, dict) else None
    return isinstance(application_changes, dict) and application_changes.get("operation") == "create"


def _canonicalize_accepted_sent_history(*, existing) -> bool:
    """Keep one accepted history row for a direct Sent application.

    Action history records the action that actually happened. A proposal that
    created an application therefore remains ``Create application`` while Gmail
    provenance is stored in ``changes.activity``. Only proposal-less/no-op Sent
    processing is represented by the generic ``Gmail activity`` type.

    A deleted application can leave an accepted create proposal orphaned. After
    the application is recreated, prefer the accepted proposal that points to
    the current application and move older orphaned create attempts out of
    Action history as superseded.
    """
    accepted = existing.filter(status=ProposalStatus.ACCEPTED).order_by("-reviewed_at", "-pk")
    canonical = accepted.filter(application__isnull=False).first() or accepted.first()
    if canonical is None:
        return False

    update_fields: list[str] = []
    if canonical.proposal_type == ProposalType.ACTIVITY and _has_created_application(canonical):
        canonical.proposal_type = ProposalType.CREATE_APPLICATION
        update_fields.append("proposal_type")

    activity_changes = _activity_changes(canonical)
    if canonical.changes != activity_changes:
        canonical.changes = activity_changes
        update_fields.append("changes")

    if not canonical.review_note.strip():
        canonical.review_note = "Recorded with Gmail Sent provenance after the application action was accepted."
        update_fields.append("review_note")

    if update_fields:
        canonical.save(update_fields=[*update_fields, "updated_at"])

    stale_orphaned = accepted.filter(
        proposal_type=ProposalType.CREATE_APPLICATION,
        application__isnull=True,
    ).exclude(pk=canonical.pk)
    if stale_orphaned.exists():
        stale_orphaned.update(
            status=ProposalStatus.IGNORED,
            review_note="Superseded after the deleted application was recreated from the same Gmail message.",
            updated_at=timezone.now(),
        )
    return True


def _find_existing_recreated_application(*, user, message, application_changes: dict):
    """Return one clearly equivalent persisted application for an orphaned Sent create.

    Recovery runs only after an application previously created from this Gmail
    message has been deleted.  Before proposing another create, check whether the
    same application was already recreated through another path.  Matching is
    deliberately conservative: company and title must both match by normalized
    equality/containment, the application must be close to the Sent timestamp,
    and exactly one candidate may qualify.
    """
    from apps.applications.models import JobApplication
    from apps.gmail_assistant.services.application_matcher import normalize_company, normalize_position

    company = normalize_company(str(application_changes.get("company") or ""))
    title = normalize_position(str(application_changes.get("title") or ""))
    if not company or not title:
        return None

    candidates = []
    applications = JobApplication.objects.filter(user=user).exclude(status__in=("archived", "rejected"))
    for application in applications:
        application_company = normalize_company(application.company)
        application_title = normalize_position(application.title)
        company_matches = bool(
            application_company
            and (company == application_company or company in application_company or application_company in company)
        )
        title_matches = bool(
            application_title
            and (title == application_title or title in application_title or application_title in title)
        )
        if not company_matches or not title_matches:
            continue
        if abs(application.applied_at - message.received_at) > timedelta(days=7):
            continue
        candidates.append(application)

    return candidates[0] if len(candidates) == 1 else None


def _relink_recreated_application(*, existing, stale_create, application, message) -> None:
    """Attach canonical Sent history to an existing application and retire stale recovery UI."""
    stale_create.application = application
    stale_create.save(update_fields=["application", "updated_at"])

    if message.application_id != application.pk:
        message.application = application
        message.save(update_fields=["application", "updated_at"])

    existing.filter(
        proposal_type=ProposalType.CREATE_APPLICATION,
        status=ProposalStatus.PENDING,
    ).update(
        status=ProposalStatus.IGNORED,
        review_note="Existing application matched; duplicate recovery proposal was retired automatically.",
        reviewed_at=timezone.now(),
        updated_at=timezone.now(),
    )


@receiver(post_save, sender=GmailAssistantSettings)
def record_proposal_less_sent_activity(
    sender,
    instance: GmailAssistantSettings,
    created: bool,
    update_fields,
    **kwargs,
) -> None:
    """Materialize canonical direct-Sent history after a successful sync.

    The normal proposal builder remains authoritative. If an accepted create
    proposal lost its application because that application was deleted, first
    reconnect it to an equivalent application that already exists. Only when no
    unique persisted match exists is a new pending create proposal restored for
    review. Accepted application actions keep their semantic proposal type in
    Action history and receive Gmail provenance; only direct-Sent messages with
    no application action become generic activity rows.
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
        has_current_accepted_application = existing.filter(
            status=ProposalStatus.ACCEPTED,
            application__isnull=False,
        ).exists()
        if stale_accepted_create is not None and not has_current_accepted_application:
            application_changes = stale_accepted_create.changes.get("application")
            if isinstance(application_changes, dict) and application_changes.get("operation") == "create":
                recreated_application = _find_existing_recreated_application(
                    user=instance.user,
                    message=analysis.message,
                    application_changes=application_changes,
                )
                if recreated_application is not None:
                    _relink_recreated_application(
                        existing=existing,
                        stale_create=stale_accepted_create,
                        application=recreated_application,
                        message=analysis.message,
                    )
                    _canonicalize_accepted_sent_history(existing=existing)
                    continue
                if not has_pending_create:
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

        if _canonicalize_accepted_sent_history(existing=existing):
            continue

        if has_pending_create or existing.exclude(proposal_type=ProposalType.ACTIVITY).exists():
            continue
        if existing.filter(proposal_type=ProposalType.ACTIVITY).exists():
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
