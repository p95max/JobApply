import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


def test_public_root_renders_landing_page(client):
    response = client.get(reverse("landing"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Keep every application, interview and recruiter email under control." in content
    assert "Continue with Google" in content
    assert "Application tracking" in content
    assert "AI Gmail Assistant" in content
    assert "Reliable backups" in content


@pytest.mark.django_db
def test_authenticated_root_redirects_to_dashboard(client):
    user = get_user_model().objects.create_user(
        username="landing-user",
        email="landing-user@example.com",
        password="test-password",
    )
    client.force_login(user)

    response = client.get(reverse("landing"))

    assert response.status_code == 302
    assert response.url == "/dashboard/"
