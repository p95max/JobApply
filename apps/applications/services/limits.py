from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model

from apps.applications.models import JobApplication


class ApplicationLimitError(RuntimeError):
    pass


def ensure_application_capacity(*, user, create_count: int = 1) -> None:
    """Enforce the per-user application cap inside the caller's transaction."""
    if create_count < 0:
        raise ValueError("create_count must not be negative")
    if create_count == 0:
        return

    get_user_model().objects.select_for_update().get(pk=user.pk)
    existing_count = JobApplication.objects.filter(user=user).count()
    if existing_count + create_count > settings.APPLICATIONS_PER_USER_LIMIT:
        raise ApplicationLimitError(
            f"Application limit reached ({settings.APPLICATIONS_PER_USER_LIMIT} per account)."
        )
