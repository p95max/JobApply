from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.gmail_stats.models import GmailSyncState
from apps.gmail_stats.services.sync_control import (
    GmailSyncBusyError,
    GmailSyncCooldownError,
    acquire_gmail_sync_lock,
    claim_manual_sync_slot,
)


@pytest.mark.django_db
@override_settings(GMAIL_SYNC_MANUAL_COOLDOWN_SECONDS=60)
def test_manual_gmail_sync_has_a_per_user_cooldown(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")

    claim_manual_sync_slot(user=user)

    with pytest.raises(GmailSyncCooldownError) as error:
        claim_manual_sync_slot(user=user)

    assert 1 <= error.value.retry_after_seconds <= 60


@pytest.mark.django_db
def test_gmail_sync_lock_blocks_a_second_run_for_the_same_user(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")

    with acquire_gmail_sync_lock(user=user):
        with pytest.raises(GmailSyncBusyError):
            with acquire_gmail_sync_lock(user=user):
                pass

    state = GmailSyncState.objects.get(user=user)
    assert state.sync_started_at is None
    assert state.sync_lock_token == ""


@pytest.mark.django_db
@override_settings(GMAIL_SYNC_LOCK_TIMEOUT_SECONDS=60)
def test_stale_gmail_sync_lock_is_recovered(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    GmailSyncState.objects.create(
        user=user,
        sync_started_at=timezone.now() - timedelta(seconds=61),
        sync_lock_token="stale-lock",
    )

    with acquire_gmail_sync_lock(user=user):
        state = GmailSyncState.objects.get(user=user)
        assert state.sync_lock_token != "stale-lock"
