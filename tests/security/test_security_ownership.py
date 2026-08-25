from types import SimpleNamespace

from django.test import override_settings

from apps.security.ownership import is_configured_owner


@override_settings(TELEGRAM_OWNER_EMAIL="Owner@Example.com")
def test_configured_owner_comparison_is_case_and_whitespace_insensitive():
    assert is_configured_owner(user=SimpleNamespace(email=" owner@example.COM "))
    assert not is_configured_owner(user=SimpleNamespace(email="other@example.com"))


@override_settings(TELEGRAM_OWNER_EMAIL="")
def test_configured_owner_requires_an_owner_email():
    assert not is_configured_owner(user=SimpleNamespace(email="owner@example.com"))
