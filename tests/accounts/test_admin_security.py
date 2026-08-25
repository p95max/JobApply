from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse


@pytest.fixture(autouse=True)
def clear_admin_security_cache():
    cache.clear()


@pytest.mark.django_db
@override_settings(
    TURNSTILE_ENABLED=False,
    ADMIN_LOGIN_MAX_FAILURES=2,
    ADMIN_LOGIN_FAILURE_WINDOW_SECONDS=300,
)
def test_admin_password_login_is_throttled_after_repeated_failures(client):
    login_url = reverse("admin:login")
    request_meta = {"REMOTE_ADDR": "198.51.100.30"}

    first = client.post(login_url, {"username": "admin", "password": "wrong"}, **request_meta)
    second = client.post(login_url, {"username": "admin", "password": "wrong"}, **request_meta)
    third = client.post(login_url, {"username": "admin", "password": "wrong"}, **request_meta)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert b"Too many failed admin sign-in attempts" in third.content


@pytest.mark.django_db
@override_settings(
    TURNSTILE_ENABLED=False,
    ADMIN_LOGIN_MAX_FAILURES=2,
    ADMIN_LOGIN_FAILURE_WINDOW_SECONDS=300,
)
def test_successful_admin_login_clears_failure_counter(client):
    get_user_model().objects.create_superuser("admin", "admin@example.com", "correct-password")
    login_url = reverse("admin:login")
    request_meta = {"REMOTE_ADDR": "198.51.100.31"}

    client.post(login_url, {"username": "admin", "password": "wrong"}, **request_meta)
    success = client.post(login_url, {"username": "admin", "password": "correct-password"}, **request_meta)
    client.logout()
    after_success = client.post(login_url, {"username": "admin", "password": "wrong"}, **request_meta)

    assert success.status_code == 302
    assert after_success.status_code == 200


@pytest.mark.django_db
@override_settings(TURNSTILE_ENABLED=False, ADMIN_ALLOWED_IPS=frozenset({"198.51.100.40"}))
def test_admin_access_policy_denies_unlisted_ips(client):
    admin_url = reverse("admin:index")

    denied = client.get(admin_url, REMOTE_ADDR="198.51.100.41")
    allowed = client.get(admin_url, REMOTE_ADDR="198.51.100.40")

    assert denied.status_code == 403
    assert allowed.status_code == 302
