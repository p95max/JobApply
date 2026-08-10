from __future__ import annotations

import math
import secrets
from contextlib import contextmanager
from datetime import timedelta
from typing import Iterator

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.gmail_stats.models import GmailSyncState


class GmailSyncBusyError(RuntimeError):
    """A Gmail sync for this user is already running."""


class GmailSyncCooldownError(RuntimeError):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Gmail sync is temporarily rate limited")


def _locked_sync_state(*, user) -> GmailSyncState:
    """Serialize state creation as well as state updates for one user."""
    get_user_model().objects.select_for_update().get(pk=user.pk)
    state, _ = GmailSyncState.objects.get_or_create(user=user)
    return GmailSyncState.objects.select_for_update().get(pk=state.pk)


def claim_manual_sync_slot(*, user) -> None:
    """Rate-limit the manual sync button before it can call Google APIs."""
    now = timezone.now()
    cooldown = settings.GMAIL_SYNC_MANUAL_COOLDOWN_SECONDS
    with transaction.atomic():
        state = _locked_sync_state(user=user)
        if state.last_manual_sync_requested_at:
            available_at = state.last_manual_sync_requested_at + timedelta(seconds=cooldown)
            if available_at > now:
                raise GmailSyncCooldownError(
                    max(1, math.ceil((available_at - now).total_seconds()))
                )
        state.last_manual_sync_requested_at = now
        state.save(update_fields=["last_manual_sync_requested_at"])


@contextmanager
def acquire_gmail_sync_lock(*, user) -> Iterator[None]:
    """Prevent concurrent Gmail/AI runs for one user across web and workers."""
    now = timezone.now()
    expires_before = now - timedelta(seconds=settings.GMAIL_SYNC_LOCK_TIMEOUT_SECONDS)
    lock_token = secrets.token_hex(16)
    with transaction.atomic():
        state = _locked_sync_state(user=user)
        if state.sync_started_at and state.sync_started_at > expires_before:
            raise GmailSyncBusyError("A Gmail sync is already running")
        state.sync_started_at = now
        state.sync_lock_token = lock_token
        state.save(update_fields=["sync_started_at", "sync_lock_token"])
    try:
        yield
    finally:
        GmailSyncState.objects.filter(user=user, sync_lock_token=lock_token).update(
            sync_started_at=None,
            sync_lock_token="",
        )
