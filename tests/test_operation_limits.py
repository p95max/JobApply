from __future__ import annotations

import pytest
from django.utils import timezone

from apps.accounts.models import UserOperationQuota
from apps.security.operation_limits import (
    OperationCooldownError,
    OperationDailyLimitError,
    OperationLimit,
    claim_user_operation,
)


@pytest.mark.django_db
def test_expensive_operation_has_a_per_user_cooldown(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    limit = OperationLimit(daily_limit=2, cooldown_seconds=60)

    claim_user_operation(user=user, operation="csv_import", limit=limit)

    with pytest.raises(OperationCooldownError):
        claim_user_operation(user=user, operation="csv_import", limit=limit)


@pytest.mark.django_db
def test_expensive_operation_stops_at_daily_limit(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    limit = OperationLimit(daily_limit=1, cooldown_seconds=0)

    claim_user_operation(user=user, operation="drive_mutation", limit=limit)

    with pytest.raises(OperationDailyLimitError):
        claim_user_operation(user=user, operation="drive_mutation", limit=limit)

    quota = UserOperationQuota.objects.get(user=user, operation="drive_mutation")
    assert quota.usage_date == timezone.localdate()
    assert quota.count == 1
