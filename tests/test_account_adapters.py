from __future__ import annotations

from types import SimpleNamespace

from apps.accounts.adapters import CustomSocialAccountAdapter


def _social_login(email: str):
    return SimpleNamespace(
        account=SimpleNamespace(extra_data={"email": email}),
        user=SimpleNamespace(email=email),
    )


def test_empty_account_allow_list_allows_google_sign_in(monkeypatch):
    monkeypatch.delenv("ALLOWED_ACCOUNT_EMAILS", raising=False)

    assert CustomSocialAccountAdapter()._is_allowed(_social_login("new@example.com"))


def test_configured_account_allow_list_restricts_google_sign_in(monkeypatch):
    monkeypatch.setenv("ALLOWED_ACCOUNT_EMAILS", "owner@example.com, allowed@example.com")
    adapter = CustomSocialAccountAdapter()

    assert adapter._is_allowed(_social_login("allowed@example.com"))
    assert not adapter._is_allowed(_social_login("other@example.com"))
