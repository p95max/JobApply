from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import connection

from apps.applications.models import ApplicationStatus, JobApplication
from apps.gmail_assistant.models import ApplicationUpdateProposal, ProposalStatus


@dataclass(frozen=True)
class StatusSnapshot:
    database_ok: bool
    total_applications: int
    pending_proposals: int


def get_owner(email: str):
    return get_user_model().objects.get(email__iexact=email)


def get_status_snapshot(email: str) -> StatusSnapshot:
    user = get_owner(email)
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        database_ok = cursor.fetchone() == (1,)
    return StatusSnapshot(
        database_ok=database_ok,
        total_applications=JobApplication.objects.filter(user=user).count(),
        pending_proposals=ApplicationUpdateProposal.objects.filter(
            user=user,
            status=ProposalStatus.PENDING,
        ).count(),
    )


def get_gmail_summary(email: str, limit: int = 5) -> tuple[int, list[ApplicationUpdateProposal]]:
    user = get_owner(email)
    queryset = (
        ApplicationUpdateProposal.objects.filter(user=user, status=ProposalStatus.PENDING)
        .select_related("application", "analysis")
        .order_by("-created_at")
    )
    return queryset.count(), list(queryset[:limit])


def get_application_summary(email: str) -> dict[str, int]:
    user = get_owner(email)
    queryset = JobApplication.objects.filter(user=user)
    result = {"total": queryset.count()}
    for status, _label in ApplicationStatus.choices:
        result[status] = queryset.filter(status=status).count()
    return result
