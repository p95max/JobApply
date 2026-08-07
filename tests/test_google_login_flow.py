from urllib.parse import parse_qs, urlparse

import pytest
from django.conf import settings
from django.urls import reverse
from django.test import override_settings


@pytest.mark.django_db
@override_settings(TURNSTILE_ENABLED=False)
def test_google_login_redirects_straight_to_oauth_without_turnstile(client):
    response = client.get(f"{reverse('google_login_gate')}?next=/applications/")

    assert response.status_code == 302
    parsed = urlparse(response["Location"])
    assert parsed.path == reverse("google_oauth_login")
    assert parse_qs(parsed.query) == {"next": ["/applications/"]}


@pytest.mark.django_db
@override_settings(TURNSTILE_ENABLED=False)
def test_google_login_drops_external_return_url(client):
    response = client.get(f"{reverse('google_login_gate')}?next=https://example.invalid/phishing")

    assert response.status_code == 302
    assert parse_qs(urlparse(response["Location"]).query) == {"next": ["/dashboard/"]}


def test_allauth_does_not_show_a_second_login_confirmation_page():
    assert settings.SOCIALACCOUNT_LOGIN_ON_GET is True
