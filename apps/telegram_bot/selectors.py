from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.applications.models import ApplicationStatus, JobApplication
from apps.gmail_assistant.models import ApplicationUpdateProposal, ProposalStatus
from apps.gmail_stats.models import GmailSyncState
from apps.interviews.models import InterviewEvent, InterviewStatus
from apps.telegram_bot.heartbeat import (
    BACKUP_WORKER,
    GMAIL_WORKER,
    TELEGRAM_BOT,
    HeartbeatStatus,
    get_heartbeat_status,
)


@dataclass(frozen=True)
class StatusSnapshot:
    database_ok: bool
    active_user_count: int
    pending_proposals: int
    commit_sha: str
    last_gmail_sync_at: datetime | None
    next_gmail_check_at: datetime | None
    commit_at: datetime | None = None
    worker_heartbeats: tuple[HeartbeatStatus, ...] = ()


@dataclass(frozen=True)
class ApplicationSummary:
    counts: dict[str, int]
    next_interview: InterviewEvent | None


def get_owner(email: str):
    return get_user_model().objects.get(email__iexact=email)


def get_new_users(days: int = 7):
    since = timezone.now() - timedelta(days=days)
    return list(
        get_user_model()
        .objects.filter(is_active=True, date_joined__gte=since)
        .only("email", "date_joined")
        .order_by("-date_joined", "-id")
    )


def _current_commit() -> tuple[str, datetime | None]:
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%h%n%cI", "HEAD"],
            cwd=Path(settings.BASE_DIR),
            capture_output=True,
            check=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown", None

    lines = result.stdout.strip().splitlines()
    commit_sha = lines[0].strip() if lines else "unknown"
    commit_at = None
    if len(lines) > 1:
        try:
            commit_at = datetime.fromisoformat(lines[1].strip())
        except ValueError:
            commit_at = None
    return commit_sha or "unknown", commit_at


def _current_commit_sha() -> str:
    return _current_commit()[0]


def get_status_snapshot(email: str) -> StatusSnapshot:
    user = get_owner(email)
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        database_ok = cursor.fetchone() == (1,)

    sync_state = GmailSyncState.objects.filter(user=user).only("last_synced_at").first()
    last_sync = sync_state.last_synced_at if sync_state else None
    interval_seconds = int(getattr(settings, "GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS", 900))
    next_check = last_sync + timedelta(seconds=interval_seconds) if last_sync else None
    commit_sha, commit_at = _current_commit()

    return StatusSnapshot(
        database_ok=database_ok,
        active_user_count=get_user_model().objects.filter(is_active=True).count(),
        pending_proposals=ApplicationUpdateProposal.objects.filter(
            user=user,
            status=ProposalStatus.PENDING,
        ).count(),
        commit_sha=commit_sha,
        last_gmail_sync_at=last_sync,
        next_gmail_check_at=next_check,
        commit_at=commit_at,
        worker_heartbeats=(
            get_heartbeat_status(GMAIL_WORKER),
            get_heartbeat_status(TELEGRAM_BOT),
            get_heartbeat_status(BACKUP_WORKER),
        ),
    )


def get_gmail_summary(email: str, limit: int = 5) -> tuple[int, list[ApplicationUpdateProposal]]:
    user = get_owner(email)
    queryset = (
        ApplicationUpdateProposal.objects.filter(user=user, status=ProposalStatus.PENDING)
        .select_related("application", "analysis", "message")
        .order_by("-created_at")
    )
    return queryset.count(), list(queryset[:limit])


def get_application_summary(email: str) -> ApplicationSummary:
    user = get_owner(email)
    queryset = JobApplication.objects.filter(user=user)
    counts = {"total": queryset.count()}
    for status, _label in ApplicationStatus.choices:
        counts[status] = queryset.filter(status=status).count()

    next_interview = (
        InterviewEvent.objects.filter(
            user=user,
            status=InterviewStatus.SCHEDULED,
            starts_at__gte=timezone.now(),
        )
        .select_related("application")
        .order_by("starts_at")
        .first()
    )
    return ApplicationSummary(counts=counts, next_interview=next_interview)
