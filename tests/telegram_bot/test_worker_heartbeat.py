from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.telegram_bot.heartbeat import GMAIL_WORKER, get_heartbeat_status, record_heartbeat
from apps.telegram_bot.models import WorkerHeartbeat


@pytest.mark.django_db
def test_record_heartbeat_creates_and_updates_worker():
    record_heartbeat(GMAIL_WORKER, expected_interval_seconds=900, success=True)
    heartbeat = WorkerHeartbeat.objects.get(worker_name=GMAIL_WORKER)

    assert heartbeat.expected_interval_seconds == 900
    assert heartbeat.last_success_at is not None
    assert heartbeat.last_error_message == ""
    assert get_heartbeat_status(GMAIL_WORKER).is_stale is False


@pytest.mark.django_db
def test_heartbeat_is_stale_after_interval_and_grace():
    heartbeat = record_heartbeat(GMAIL_WORKER, expected_interval_seconds=60, success=True)
    WorkerHeartbeat.objects.filter(pk=heartbeat.pk).update(last_seen_at=timezone.now() - timedelta(seconds=121))

    assert get_heartbeat_status(GMAIL_WORKER).is_stale is True


@pytest.mark.django_db
def test_heartbeat_keeps_safe_error_category():
    record_heartbeat(GMAIL_WORKER, expected_interval_seconds=60, success=False, error=RuntimeError("secret"))

    heartbeat = WorkerHeartbeat.objects.get(worker_name=GMAIL_WORKER)
    assert heartbeat.last_error_message == "RuntimeError"
