import hashlib
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.accounts.telegram_linking import bind_telegram_from_start
from apps.telegram_bot.config import TelegramConfig
from apps.telegram_bot.permissions import is_update_allowed


@pytest.fixture
def account(db):
    user = get_user_model().objects.create_user(
        username="settings-owner",
        email="settings-owner@example.com",
        password="test-password",
    )
    profile = UserProfile.objects.create(
        user=user,
        google_data_access_consent=True,
        consent_accepted_at=timezone.now(),
    )
    return user, profile


def _update(token: str, *, user_id: int = 200, chat_id: int = 100):
    return {
        "message": {
            "text": f"/start {token}",
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": user_id},
        }
    }


def test_one_time_token_binds_private_telegram_chat(account):
    _user, profile = account
    token = profile.create_telegram_link_token()

    linked = bind_telegram_from_start(_update(token))

    assert linked is not None
    profile.refresh_from_db()
    assert profile.telegram_user_id == 200
    assert profile.telegram_chat_id == 100
    assert profile.telegram_link_token_hash == ""
    assert bind_telegram_from_start(_update(token)) is None


def test_invalid_link_token_does_not_bind(account):
    _user, profile = account
    profile.create_telegram_link_token()

    assert bind_telegram_from_start(_update("wrong-token")) is None
    profile.refresh_from_db()
    assert profile.telegram_chat_id is None


def test_linked_ids_are_authorized_without_env_allowlist(account):
    _user, profile = account
    profile.telegram_user_id = 200
    profile.telegram_chat_id = 100
    profile.telegram_linked_at = timezone.now()
    profile.save(update_fields=["telegram_user_id", "telegram_chat_id", "telegram_linked_at"])
    config = TelegramConfig(
        enabled=True,
        token="token",
        default_chat_id=None,
        allowed_chat_ids=frozenset(),
        allowed_user_ids=frozenset(),
        owner_email="settings-owner@example.com",
        environment_label="TEST",
        notifications_enabled=True,
    )

    assert is_update_allowed(_update("unused"), config) is True


@override_settings(TELEGRAM_BOT_USERNAME="jobapply_test_bot")
def test_settings_generates_hashed_telegram_link(client, account):
    user, profile = account
    client.force_login(user)

    response = client.post(reverse("accounts:settings"), {"action": "telegram_link"}, follow=True)

    assert response.status_code == 200
    profile.refresh_from_db()
    assert profile.telegram_link_token_hash
    assert len(profile.telegram_link_token_hash) == len(hashlib.sha256(b"x").hexdigest())
    content = response.content.decode()
    assert "https://t.me/jobapply_test_bot?start=" in content
    assert "/start " in content
    assert "return here and reload this page" in content


def test_gmail_status_tab_hides_credentials(client, account):
    user, _profile = account
    client.force_login(user)

    with patch(
        "apps.accounts.views.get_google_credentials_for_user",
        return_value=object(),
    ):
        response = client.get(reverse("accounts:settings") + "?tab=gmail")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Gmail status" in content
    assert "Connected" in content
    assert "refresh_token" not in content
    assert "access_token" not in content
