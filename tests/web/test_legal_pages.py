from __future__ import annotations

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import UserProfile


@pytest.mark.parametrize(
    ("url_name", "expected"),
    [
        ("legal:impressum", b"Impressum"),
        ("legal:privacy", b"Datenschutz"),
        ("legal:terms", b"Nutzungsbedingungen"),
    ],
)
@override_settings(TURNSTILE_ENABLED=True)
def test_legal_pages_are_public(client, url_name, expected):
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "de"

    response = client.get(reverse(url_name))

    assert response.status_code == 200
    assert expected in response.content


@override_settings(
    LEGAL_PROVIDER_NAME="Max Mustermann",
    LEGAL_PROVIDER_ADDRESS="Musterstrasse 1\n12345 Berlin",
    LEGAL_CONTACT_EMAIL="contact@example.com",
    LEGAL_PRIVACY_CONTACT_EMAIL="privacy@example.com",
    LEGAL_SUPERVISORY_AUTHORITY="Berliner Beauftragte fuer Datenschutz",
    LEGAL_LOG_RETENTION="14 Tage",
    DEMO_ACCOUNT_TTL_HOURS=12,
)
def test_privacy_page_uses_configured_legal_details(client):
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "de"

    response = client.get(reverse("legal:privacy"))

    assert response.status_code == 200
    assert b"Max Mustermann" in response.content
    assert b"privacy@example.com" in response.content
    assert b"14 Tage" in response.content
    assert b"Google-Drive-Backups" in response.content
    assert b"beschr\xc3\xa4nkten <code>drive.file</code>-Zugriff" in response.content
    assert b"jobapply_cookie_notice" in response.content
    assert b"12 Stunden" in response.content
    assert b"Demo-Placeholder" not in response.content
    assert response.content.count(b"Optionale AI-Analyse") == 1
    assert b"erst nach einer Best\xc3\xa4tigung durch den Nutzer" not in response.content


@pytest.mark.django_db
def test_legal_pages_are_available_before_consent(client):
    user = get_user_model().objects.create_user("before-consent", email="before-consent@example.com")
    UserProfile.objects.create(user=user, google_data_access_consent=False)
    client.force_login(user)

    response = client.get(reverse("legal:privacy"))

    assert response.status_code == 200


@override_settings(DEMO_ACCOUNT_TTL_HOURS=18)
def test_legal_pages_use_english_when_english_is_selected(client):
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"

    privacy = client.get(reverse("legal:privacy"))
    impressum = client.get(reverse("legal:impressum"))
    terms = client.get(reverse("legal:terms"))

    assert b"Privacy Policy" in privacy.content
    assert b"Google Drive backups" in privacy.content
    assert b"limited <code>drive.file</code> access" in privacy.content
    assert b"jobapply_cookie_notice" in privacy.content
    assert b"18 hours" in privacy.content
    assert privacy.content.count(b"Optional AI analysis") == 1
    assert b"application changes require user confirmation" not in privacy.content
    assert b"Legal notice" in impressum.content
    assert b"Terms of Use" in terms.content
