import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile


@override_settings(TURNSTILE_ENABLED=True)
def test_public_root_renders_landing_page(client):
    response = client.get(reverse("landing"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "<title>JobApply</title>" in content
    assert "Keep every application, interview and recruiter email under control." in content
    assert "Continue with Google" in content
    assert "Application tracking" in content
    assert "Passwordless Google sign-in" in content
    assert "Optional AI Gmail Assistant" in content
    assert "Telegram bot notifications" in content
    assert "Google Drive backup integration" in content
    assert "control token usage" in content
    assert "How JobApply works" in content
    assert "Manual review" in content
    assert "Trusted automation" in content
    assert "Data safety" in content
    assert "AI never deletes your emails, applications or notes." in content
    assert "DEMO" in content
    assert reverse("legal:privacy") in content
    assert "data-cookie-consent-modal" in content
    assert "data-open-cookie-settings" in content


def test_favicon_redirects_to_the_jobapply_mark(client):
    response = client.get("/favicon.ico")

    assert response.status_code == 301
    assert response["Location"].endswith("/static/img/jobapply-mark.svg")


@pytest.mark.django_db
def test_authenticated_root_redirects_to_dashboard(client):
    user = get_user_model().objects.create_user(
        username="landing-user",
        email="landing-user@example.com",
        password="test-password",
    )
    UserProfile.objects.create(
        user=user,
        google_data_access_consent=True,
        consent_accepted_at=timezone.now(),
    )
    client.force_login(user)

    response = client.get(reverse("landing"))

    assert response.status_code == 302
    assert response.url == "/dashboard/"
