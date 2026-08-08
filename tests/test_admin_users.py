from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib import admin
from django.contrib.auth.models import User
from django.test import RequestFactory
from django.utils import timezone

from apps.gmail_assistant.usage_models import OpenAITokenUsage
from apps.gmail_stats.models import GmailMessage


@pytest.mark.django_db
def test_user_admin_lists_only_active_users_with_last_30_days_token_usage():
    active_user = User.objects.create_user("active", email="active@example.com")
    inactive_user = User.objects.create_user("inactive", email="inactive@example.com", is_active=False)
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
    assert row.tokens_30d_input_value == recent_usage.input_tokens
    assert row.tokens_30d_output_value == recent_usage.output_tokens
    assert row.tokens_30d_total_value == recent_usage.total_tokens
