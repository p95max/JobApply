from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.applications.models import JobApplication
from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailEventType,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_assistant.services.ai_policy import AIUsagePolicy
from apps.gmail_assistant.usage_models import OpenAITokenUsage
from apps.reports.models import CloudBackupSettings

from .notifications import send_notification_once

DAILY_DIGEST_HOURS = 24
WEEKLY_DIGEST_HOURS = 24 * 7


@dataclass(frozen=True)
class ClientDigest:
    since: datetime
    until: datetime
    gmail_events: int
    applications_created: int
    applications_updated: int
    pending_proposals: int
    rejections: int
    interviews: int
    offers: int
    action_required: int
    ai_requests: int
    ai_tokens: int
    ai_calls_left: int
    ai_daily_limit: int
    backup_connected: bool
    backup_enabled: bool
    last_backup_at: datetime | None

    @property
    def has_activity(self) -> bool:
        return any(
            (
                self.gmail_events,
                self.applications_created,
                self.applications_updated,
                self.rejections,
                self.interviews,
                self.offers,
                self.action_required,
                self.ai_requests,
            )
        )


def _jobapply_url(path: str) -> str:
    domain = str(getattr(settings, "DJANGO_SITE_DOMAIN", "jobapply.p95max.dev")).strip().strip("/")
    base = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
    return f"{base}{path}"


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "not available"
    return timezone.localtime(value).strftime("%d.%m.%Y %H:%M")


def build_client_digest(*, user, hours: int, until: datetime | None = None) -> ClientDigest:
    until = until or timezone.now()
    since = until - timedelta(hours=hours)

    analyses = GmailAnalysis.objects.filter(
        user=user,
        is_job_related=True,
        analyzed_at__gte=since,
        analyzed_at__lte=until,
    )
    proposals = ApplicationUpdateProposal.objects.filter(
        user=user,
        created_at__gte=since,
        created_at__lte=until,
    )
    applications_updated = ApplicationUpdateProposal.objects.filter(
        user=user,
        proposal_type=ProposalType.UPDATE_APPLICATION,
        status=ProposalStatus.ACCEPTED,
        reviewed_at__gte=since,
        reviewed_at__lte=until,
    ).count()

    token_totals = OpenAITokenUsage.objects.filter(
        user=user,
        created_at__gte=since,
        created_at__lte=until,
    ).aggregate(
        requests=Count("id"),
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
    )
    policy = AIUsagePolicy.from_environment()
    used_calls = policy.daily_usage(user=user)
    backup = CloudBackupSettings.objects.filter(user=user).only(
        "drive_connected", "enabled", "last_run_at"
    ).first()

    return ClientDigest(
        since=since,
        until=until,
        gmail_events=analyses.count(),
        applications_created=JobApplication.objects.filter(
            user=user,
            created_at__gte=since,
            created_at__lte=until,
        ).count(),
        applications_updated=applications_updated,
        pending_proposals=ApplicationUpdateProposal.objects.filter(
            user=user,
            status=ProposalStatus.PENDING,
        ).count(),
        rejections=analyses.filter(event_type=GmailEventType.REJECTION).count(),
        interviews=analyses.filter(
            event_type__in=(
                GmailEventType.INTERVIEW_INVITATION,
                GmailEventType.INTERVIEW_RESCHEDULED,
            )
        ).count(),
        offers=analyses.filter(event_type=GmailEventType.OFFER).count(),
        action_required=proposals.filter(proposal_type=ProposalType.ACTION_REQUIRED).count(),
        ai_requests=int(token_totals["requests"] or 0),
        ai_tokens=int(token_totals["input_tokens"] or 0) + int(token_totals["output_tokens"] or 0),
        ai_calls_left=max(0, policy.daily_limit - used_calls),
        ai_daily_limit=policy.daily_limit,
        backup_connected=bool(backup and backup.drive_connected),
        backup_enabled=bool(backup and backup.enabled),
        last_backup_at=backup.last_run_at if backup else None,
    )


def client_digest_text(digest: ClientDigest, *, scheduled: bool = False) -> str:
    hours = max(1, round((digest.until - digest.since).total_seconds() / 3600))
    if hours >= WEEKLY_DIGEST_HOURS:
        title = "JobApply digest · last 7 days"
    elif scheduled:
        title = "Daily JobApply digest · last 24h"
    else:
        title = "JobApply digest · last 24h"

    lines = [f"📊 <b>{title}</b>", ""]
    if not digest.has_activity:
        lines.append("✅ No new activity in this period.")
        lines.append(f"⏳ Pending proposals: <b>{digest.pending_proposals}</b>")
    else:
        lines.extend(
            [
                f"📨 Gmail events: <b>{digest.gmail_events}</b>",
                f"✨ Applications created: <b>{digest.applications_created}</b>",
                f"🔄 Applications updated: <b>{digest.applications_updated}</b>",
                f"⏳ Pending proposals: <b>{digest.pending_proposals}</b>",
                "",
                f"❌ Rejections: <b>{digest.rejections}</b>",
                f"📅 Interviews: <b>{digest.interviews}</b>",
                f"💼 Offers: <b>{digest.offers}</b>",
                f"⚠️ Action required: <b>{digest.action_required}</b>",
                "",
                f"🤖 AI calls: <b>{digest.ai_requests}</b>",
                f"🪙 Tokens: <b>{digest.ai_tokens:,}</b>",
                f"⚡ AI quota left today: <b>{digest.ai_calls_left}/{digest.ai_daily_limit}</b>",
            ]
        )

    lines.append("")
    if not digest.backup_connected:
        lines.append("☁️ Backup: <b>Google Drive not connected</b>")
    elif not digest.backup_enabled:
        lines.append("☁️ Backup: <b>automatic backup off</b>")
    elif digest.last_backup_at is None:
        lines.append("☁️ Backup: <b>waiting for first successful backup</b>")
    else:
        lines.append(f"☁️ Last backup: ✅ <b>{escape(_format_dt(digest.last_backup_at))}</b>")

    return "\n".join(lines)


def client_digest_keyboard(*, hours: int) -> dict[str, list[list[dict[str, str]]]]:
    if hours >= WEEKLY_DIGEST_HOURS:
        period_button = {"text": "↩️ Last 24 hours", "callback_data": "digest:24"}
    else:
        period_button = {"text": "📅 Digest for 7 days", "callback_data": "digest:168"}
    return {
        "inline_keyboard": [
            [
                {
                    "text": "📨 Open Gmail Assistant",
                    "url": _jobapply_url("/gmail_stats/gmail/assistant/"),
                }
            ],
            [period_button],
        ]
    }


def parse_digest_callback(value: object) -> int | None:
    if value == "digest:24":
        return DAILY_DIGEST_HOURS
    if value == "digest:168":
        return WEEKLY_DIGEST_HOURS
    return None


def send_daily_client_digests() -> int:
    """Send one rolling-24h digest per linked, active, non-demo user."""
    today = timezone.localdate().isoformat()
    sent = 0
    profiles = (
        UserProfile.objects.select_related("user")
        .filter(
            user__is_active=True,
            is_demo_user=False,
            telegram_chat_id__isnull=False,
        )
        .exclude(user__email="")
    )
    for profile in profiles.iterator():
        user = profile.user
        digest = build_client_digest(user=user, hours=DAILY_DIGEST_HOURS)
        if send_notification_once(
            event_key=f"client_daily_digest:{user.pk}:{today}",
            event_type="client_daily_digest",
            recipient_email=user.email,
            text=client_digest_text(digest, scheduled=True),
            reply_markup=client_digest_keyboard(hours=DAILY_DIGEST_HOURS),
        ):
            sent += 1
    return sent
