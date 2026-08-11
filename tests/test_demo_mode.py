from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import UserProfile


@pytest.fixture(autouse=True)
def clear_demo_start_cache():
    cache.clear()


@pytest.mark.django_db(transaction=True)
@override_settings(TURNSTILE_ENABLED=False, DEMO_ACCOUNT_TTL_HOURS=12)
@patch("apps.accounts.views.send_notification_once")
def test_guest_can_start_temporary_demo_and_use_manual_workspace(send_notification_mock, client):
    landing = client.get(reverse("landing"))
    response = client.post(reverse("accounts:start_demo"))

    assert reverse("accounts:start_demo").encode() in landing.content
    assert response.status_code == 302
    assert response.url == reverse("dashboard")
    user_id = client.session.get("_auth_user_id")
    profile = UserProfile.objects.get(user_id=user_id)
    user = get_user_model().objects.get(pk=user_id)
    assert profile.is_demo_user is True
    assert user.username.startswith("demo-")
    assert client.session.get_expiry_age() <= 12 * 60 * 60
    send_notification_mock.assert_called_once_with(
        event_key=f"demo_started:{user.pk}",
        event_type="demo_started",
        text=(
            "🧪 <b>Demo mode started</b>\n\n"
            f"👤 Workspace: <code>{user.username}</code>\n"
            "⏳ Auto-delete after: <b>12 hours</b>"
        ),
    )

    dashboard = client.get(reverse("dashboard"))
    application_form = client.get(reverse("applications:create"))

    assert b"Sign in with Google" in dashboard.content
    assert b"Gmail Assistant" in dashboard.content
    assert b"data-theme-toggle" in dashboard.content
    assert b"app-language-switch__flag" in dashboard.content
    assert application_form.status_code == 200


@pytest.mark.django_db(transaction=True)
@override_settings(TURNSTILE_ENABLED=True, DEMO_ACCOUNT_TTL_HOURS=12)
@patch("apps.accounts.views.send_notification_once")
def test_demo_start_bypasses_google_turnstile_gate(send_notification_mock, client):
    response = client.post(reverse("accounts:start_demo"))

    assert response.status_code == 302
    assert response.url == reverse("dashboard")
    user_id = client.session.get("_auth_user_id")
    assert user_id is not None
    assert UserProfile.objects.get(user_id=user_id).is_demo_user is True
    send_notification_mock.assert_called_once()


@pytest.mark.django_db
@override_settings(TURNSTILE_ENABLED=False)
def test_guest_can_open_safe_connected_service_previews(client):
    client.post(reverse("accounts:start_demo"))

    assistant = client.get(reverse("gmail_assistant:gmail_assistant"))
    reports = client.get(reverse("reports:statistics"))

    assert assistant.status_code == 200
    assert b"Gmail Assistant preview" in assistant.content
    assert reports.status_code == 200
    assert b"Reports preview" in reports.content


@pytest.mark.django_db
@override_settings(TURNSTILE_ENABLED=False)
def test_guest_cannot_start_google_oauth_or_post_to_connected_services(client):
    client.post(reverse("accounts:start_demo"))

    oauth = client.get("/accounts/google/login/")
    connected_action = client.post(reverse("gmail_assistant:gmail_assistant_settings"))

    assert oauth.status_code == 302
    assert oauth.url == reverse("dashboard")
    assert connected_action.status_code == 302
    assert connected_action.url == reverse("dashboard")


@pytest.mark.django_db
@override_settings(TURNSTILE_ENABLED=False)
def test_google_login_leaves_demo_workspace_before_oauth(client):
    client.post(reverse("accounts:start_demo"))

    response = client.post(reverse("accounts:start_full_login"))

    assert response.status_code == 302
    assert response.url == "/accounts/google/login/?next=/dashboard/"
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
@override_settings(
    TURNSTILE_ENABLED=False,
    DEMO_START_MAX_PER_IP_PER_DAY=1,
    DEMO_START_COOLDOWN_SECONDS=0,
)
def test_demo_start_is_limited_per_untrusted_client_ip(client):
    cache.clear()
    remote_ip = "198.51.100.42"

    first = client.post(reverse("accounts:start_demo"), REMOTE_ADDR=remote_ip)
    client.logout()
    second = client.post(
        reverse("accounts:start_demo"),
        REMOTE_ADDR=remote_ip,
        HTTP_X_FORWARDED_FOR="203.0.113.99",
    )

    assert first.status_code == 302
    assert second.status_code == 302
    assert second.url == reverse("landing")
    assert UserProfile.objects.filter(is_demo_user=True).count() == 1
