import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile


def test_public_root_renders_landing_page(client):
    response = client.get(reverse("landing"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Keep every application, interview and recruiter email under control." in content
    assert "Continue with Google" in content
    assert "Application tracking" in content
    assert "Passwordless Google sign-in" in content
    assert "Optional AI Gmail Assistant" in content
    assert "Telegram bot notifications" in content
    assert "Google Drive backup integration" in content
    assert "control token usage" in content
    assert "DEMO" in content
    assert reverse("legal:privacy") in content


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
