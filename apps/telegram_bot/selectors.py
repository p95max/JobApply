from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import Count, Sum
from django.utils import timezone

from apps.applications.models import ApplicationStatus, JobApplication
from apps.gmail_assistant.models import ApplicationUpdateProposal, ProposalStatus
from apps.gmail_assistant.services.ai_policy import AIUsagePolicy
from apps.gmail_assistant.services.token_usage import estimate_model_cost
from apps.gmail_assistant.usage_models import OpenAITokenUsage
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


@dataclass(frozen=True)
class AIUsageSummary:
    calls_left: int
    daily_limit: int
    tokens_used_today: int


@dataclass(frozen=True)
class AIUsageUserSummary:
    email: str
    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    calls_left: int
    daily_limit: int


@dataclass(frozen=True)
class AIUsageDigest:
    since: datetime
    until: datetime
    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: Decimal | None
    active_user_count: int
    top_users: tuple[AIUsageUserSummary, ...]


def get_owner(email: str):
    return get_user_model().objects.get(email__iexact=email)


def get_new_users(days: int = 7):
    since = timezone.now() - timedelta(days=days)
    base_queryset = get_user_model().objects.filter(is_active=True, date_joined__gte=since)
    demo_count = base_queryset.filter(userprofile__is_demo_user=True).count()
    users = list(
        base_queryset.exclude(userprofile__is_demo_user=True)
        .only("email", "date_joined")
        .order_by("-date_joined", "-id")
    )
    return users, demo_count


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


def get_ai_usage_summary(email: str) -> AIUsageSummary:
    user = get_owner(email)
    policy = AIUsagePolicy.from_environment()
    used_calls = policy.daily_usage(user=user)
    token_totals = OpenAITokenUsage.objects.filter(
        user=user,
        created_at__date=timezone.localdate(),
    ).aggregate(
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
    )
    tokens_used_today = int(token_totals["input_tokens"] or 0) + int(token_totals["output_tokens"] or 0)
    return AIUsageSummary(
        calls_left=max(0, policy.daily_limit - used_calls),
        daily_limit=policy.daily_limit,
        tokens_used_today=tokens_used_today,
    )


def get_ai_usage_digest(*, hours: int = 24, top_limit: int = 5) -> AIUsageDigest:
    """Return persisted successful OpenAI usage for a rolling time window across all users."""
    until = timezone.now()
    since = until - timedelta(hours=hours)
    queryset = OpenAITokenUsage.objects.filter(created_at__gte=since, created_at__lte=until)
    totals = queryset.aggregate(
        requests=Count("id"),
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
    )
    input_tokens = int(totals["input_tokens"] or 0)
    output_tokens = int(totals["output_tokens"] or 0)

    model_rows = queryset.values("model_name").annotate(
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
    )
    model_costs = [
        estimate_model_cost(
            str(row["model_name"] or ""),
            int(row["input_tokens"] or 0),
            int(row["output_tokens"] or 0),
        )
        for row in model_rows
    ]
    estimated_cost = None if any(cost is None for cost in model_costs) else sum(model_costs, Decimal("0"))

    raw_users = list(
        queryset.values("user_id", "user__email").annotate(
            requests=Count("id"),
            input_tokens=Sum("input_tokens"),
            output_tokens=Sum("output_tokens"),
        )
    )
    raw_users.sort(
        key=lambda row: int(row["input_tokens"] or 0) + int(row["output_tokens"] or 0),
        reverse=True,
    )
    policy = AIUsagePolicy.from_environment()
    users_by_id = get_user_model().objects.in_bulk(
        [int(row["user_id"]) for row in raw_users[:top_limit]]
    )
    top_users: list[AIUsageUserSummary] = []
    for row in raw_users[:top_limit]:
        user = users_by_id.get(int(row["user_id"]))
        used_calls = policy.daily_usage(user=user) if user is not None else 0
        row_input = int(row["input_tokens"] or 0)
        row_output = int(row["output_tokens"] or 0)
        top_users.append(
            AIUsageUserSummary(
                email=str(row["user__email"] or "no email"),
                requests=int(row["requests"] or 0),
                input_tokens=row_input,
                output_tokens=row_output,
                total_tokens=row_input + row_output,
                calls_left=max(0, policy.daily_limit - used_calls),
                daily_limit=policy.daily_limit,
            )
        )

    return AIUsageDigest(
        since=since,
        until=until,
        requests=int(totals["requests"] or 0),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_usd=estimated_cost,
        active_user_count=len(raw_users),
        top_users=tuple(top_users),
    )


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
