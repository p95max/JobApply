from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.applications.models import JobApplication
from apps.gmail_stats.models import GmailSyncState
from apps.interviews.models import InterviewEvent
from apps.telegram_bot.selectors import ApplicationSummary, StatusSnapshot, get_application_summary, get_status_snapshot
from apps.telegram_bot.texts import applications_text, status_text


@pytest.mark.django_db
def test_status_snapshot_includes_commit_and_gmail_schedule(django_user_model, monkeypatch, settings):
    user = django_user_model.objects.create_user("owner", email="owner@example.com")
    JobApplication.objects.create(user=user, company="Example GmbH", title="Developer")
    synced_at = timezone.now()
    GmailSyncState.objects.create(user=user, last_synced_at=synced_at)
    settings.GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS = 900
    monkeypatch.setattr("apps.telegram_bot.selectors._current_commit_sha", lambda: "abc1234")

    snapshot = get_status_snapshot(user.email)

    assert snapshot.database_ok is True
    assert snapshot.total_applications == 1
    assert snapshot.commit_sha == "abc1234"
    assert snapshot.last_gmail_sync_at == synced_at
    assert snapshot.next_gmail_check_at == synced_at + timedelta(seconds=900)


def test_status_text_renders_stage_2_fields():
    now = timezone.now()
    text = status_text(
        "PRODUCTION",
        StatusSnapshot(
            database_ok=True,
            total_applications=3,
            pending_proposals=2,
            commit_sha="abc1234",
            last_gmail_sync_at=now,
            next_gmail_check_at=now + timedelta(minutes=15),
        ),
    )

    assert "abc1234" in text
    assert "Last Gmail sync" in text
    assert "Next Gmail check" in text


@pytest.mark.django_db
def test_application_summary_contains_next_interview(django_user_model):
    user = django_user_model.objects.create_user("owner", email="owner@example.com")
    application = JobApplication.objects.create(user=user, company="Example GmbH", title="Developer")
    InterviewEvent.objects.create(
        user=user,
        application=application,
        starts_at=timezone.now() + timedelta(days=1),
        location="Video",
    )

    summary = get_application_summary(user.email)
    text = applications_text(summary)

    assert isinstance(summary, ApplicationSummary)
    assert summary.counts["total"] == 1
    assert summary.next_interview is not None
    assert "Next interview" in text
    assert "Example GmbH" in text
