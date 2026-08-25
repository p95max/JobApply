from __future__ import annotations

from datetime import timedelta

import pytest
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.contrib import admin
from django.contrib.auth.models import User
from django.test import RequestFactory
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.applications.models import JobApplication
from apps.gmail_assistant.usage_models import OpenAITokenUsage
from apps.gmail_stats.models import GmailMessage


@pytest.mark.django_db
def test_user_admin_lists_active_users_with_usage_integrations_and_applications():
    active_user = User.objects.create_user("active", email="active@example.com")
    inactive_user = User.objects.create_user("inactive", email="inactive@example.com", is_active=False)
    UserProfile.objects.create(
        user=active_user,
        telegram_user_id=200,
        telegram_chat_id=100,
    )

    google_account = SocialAccount.objects.create(
        user=active_user,
        provider="google",
        uid="active-google",
    )
    SocialToken.objects.create(account=google_account, token="access-token")

    JobApplication.objects.create(user=active_user, title="Backend Developer", company="Example GmbH")
    JobApplication.objects.create(user=active_user, title="Python Developer", company="Other GmbH")

    message = GmailMessage.objects.create(
        user=active_user,
        message_id="admin-token-usage",
        thread_id="admin-token-usage",
        received_at=timezone.now(),
    )
    recent_usage = OpenAITokenUsage.objects.create(
        user=active_user,
        message=message,
        model_name="gpt-test",
        input_tokens=120,
        output_tokens=30,
    )
    old_usage = OpenAITokenUsage.objects.create(
        user=active_user,
        message=message,
        model_name="gpt-test",
        input_tokens=900,
        output_tokens=100,
    )
    OpenAITokenUsage.objects.filter(pk=old_usage.pk).update(
        created_at=timezone.now() - timedelta(days=31)
    )

    model_admin = admin.site._registry[User]
    request = RequestFactory().get("/admin/auth/user/")
    request.user = User.objects.create_superuser("admin", "admin@example.com", "password")
    queryset = model_admin.get_queryset(request)

    assert queryset.filter(pk=inactive_user.pk).exists() is False
    row = queryset.get(pk=active_user.pk)
    assert row.telegram_connected_value is True
    assert row.drive_connected_value is True
    assert row.applications_count_value == 2
    assert row.tokens_30d_input_value == recent_usage.input_tokens
    assert row.tokens_30d_output_value == recent_usage.output_tokens
    assert row.tokens_30d_total_value == recent_usage.total_tokens


@pytest.mark.django_db
def test_user_admin_marks_missing_integrations_as_disconnected():
    user = User.objects.create_user("plain", email="plain@example.com")
    model_admin = admin.site._registry[User]
    request = RequestFactory().get("/admin/auth/user/")
    request.user = User.objects.create_superuser("admin2", "admin2@example.com", "password")

    row = model_admin.get_queryset(request).get(pk=user.pk)

    assert row.telegram_connected_value is False
    assert row.drive_connected_value is False
    assert row.applications_count_value == 0
    assert row.tokens_30d_total_value == 0
