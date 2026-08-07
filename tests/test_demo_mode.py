from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import UserProfile


@pytest.mark.django_db
@override_settings(TURNSTILE_ENABLED=False)
def test_guest_can_start_temporary_demo_and_use_manual_workspace(client):
    landing = client.get(reverse("landing"))
    response = client.post(reverse("accounts:start_demo"))

    assert reverse("accounts:start_demo").encode() in landing.content
    assert response.status_code == 302
    assert response.url == reverse("dashboard")
    user_id = client.session.get("_auth_user_id")
    profile = UserProfile.objects.get(user_id=user_id)
    assert profile.is_demo_user is True
    assert get_user_model().objects.get(pk=user_id).username.startswith("demo-")

    dashboard = client.get(reverse("dashboard"))
    application_form = client.get(reverse("applications:create"))

    assert b"Sign in with Google" in dashboard.content
    assert b"Gmail Assistant" in dashboard.content
    assert application_form.status_code == 200


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
