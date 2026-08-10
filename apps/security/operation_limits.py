from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserOperationQuota


@dataclass(frozen=True)
class OperationLimit:
    daily_limit: int
    cooldown_seconds: int


class OperationCooldownError(RuntimeError):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Operation is temporarily rate limited")


class OperationDailyLimitError(RuntimeError):
    pass


def claim_user_operation(*, user, operation: str, limit: OperationLimit) -> None:
    """Atomically reserve an expensive user operation before it starts work."""
    now = timezone.now()
    today = timezone.localdate()
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        quota, _ = UserOperationQuota.objects.get_or_create(
            user=user,
            operation=operation,
            defaults={"usage_date": today},
        )
        quota = UserOperationQuota.objects.select_for_update().get(pk=quota.pk)
        if quota.usage_date != today:
            quota.usage_date = today
            quota.count = 0
            quota.last_used_at = None
        if quota.last_used_at:
            available_at = quota.last_used_at + timedelta(seconds=limit.cooldown_seconds)
            if available_at > now:
                raise OperationCooldownError(max(1, math.ceil((available_at - now).total_seconds())))
        if quota.count >= limit.daily_limit:
            raise OperationDailyLimitError("Daily operation limit reached")
        quota.count += 1
        quota.last_used_at = now
        quota.save(update_fields=["usage_date", "count", "last_used_at"])
