import hashlib
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TelegramLinkTokenCooldownError, UserProfile
from apps.applications.models import JobApplication
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


def _update(token: str, *, command: str = "/start", user_id: int = 200, chat_id: int = 100):
    return {
        "message": {
            "text": f"{command} {token}",
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


def test_one_time_token_binds_private_telegram_chat_from_link_command(account):
    _user, profile = account
    token = profile.create_telegram_link_token()

    linked = bind_telegram_from_start(_update(token, command="/link"))

    assert linked is not None
    profile.refresh_from_db()
    assert profile.telegram_chat_id == 100


def test_one_time_token_binds_private_telegram_chat_from_raw_code(account):
    _user, profile = account
    token = profile.create_telegram_link_token()
    update = _update(token)
    update["message"]["text"] = token

    linked = bind_telegram_from_start(update)

    assert linked is not None
    profile.refresh_from_db()
    assert profile.telegram_chat_id == 100


def test_invalid_link_token_does_not_bind(account):
    _user, profile = account
    profile.create_telegram_link_token()

    assert bind_telegram_from_start(_update("wrong-token")) is None
    profile.refresh_from_db()
    assert profile.telegram_chat_id is None


@override_settings(TELEGRAM_LINK_TOKEN_COOLDOWN_SECONDS=60)
def test_telegram_link_token_has_a_short_issuance_cooldown(account):
    _user, profile = account
    profile.create_telegram_link_token()

    with pytest.raises(TelegramLinkTokenCooldownError):
        profile.create_telegram_link_token()


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
def test_settings_generates_one_time_telegram_command_without_redirecting_to_bot(client, account):
    user, profile = account
    client.force_login(user)

    page = client.get(reverse("accounts:settings"))
    assert page.status_code == 200
    assert 'name="action" value="telegram_link"' in page.content.decode()

    response = client.post(reverse("accounts:settings"), {"action": "telegram_link"})

    assert response.status_code == 302
    assert response.url == reverse("accounts:settings")
    profile.refresh_from_db()
    assert profile.telegram_link_token_hash
    assert len(profile.telegram_link_token_hash) == len(hashlib.sha256(b"x").hexdigest())

    page = client.get(reverse("accounts:settings"))
    content = page.content.decode()
    assert "One-time connection code" in content
    assert "/link " in content
    assert "Connect automatically instead" in content

    page = client.get(reverse("accounts:settings"))
    assert "/link " in page.content.decode()


@override_settings(TELEGRAM_LINK_TOKEN_COOLDOWN_SECONDS=60)
def test_settings_rate_limits_repeated_telegram_link_token_requests(client, account):
    user, _profile = account
    client.force_login(user)

    first = client.post(reverse("accounts:settings"), {"action": "telegram_link"})
    second = client.post(reverse("accounts:settings"), {"action": "telegram_link"}, follow=True)

    assert first.status_code == 302
    assert second.status_code == 200
    assert b"requested recently" in second.content


@override_settings(TELEGRAM_BOT_USERNAME="jobapply_test_bot")
def test_disconnect_clears_binding_and_returns_to_settings(client, account):
    user, profile = account
    profile.telegram_user_id = 200
    profile.telegram_chat_id = 100
    profile.telegram_linked_at = timezone.now()
    profile.save(update_fields=["telegram_user_id", "telegram_chat_id", "telegram_linked_at"])
    client.force_login(user)

    response = client.post(reverse("accounts:settings"), {"action": "telegram_disconnect"})

    assert response.status_code == 302
    assert response.url == reverse("accounts:settings")
    profile.refresh_from_db()
    assert profile.telegram_user_id is None
    assert profile.telegram_chat_id is None
    assert profile.telegram_linked_at is None


def test_gmail_status_tab_hides_credentials_and_service_links(client, account):
    user, _profile = account
    client.force_login(user)

    with patch(
        "apps.accounts.views.get_google_credentials_for_user",
        return_value=object(),
    ):
        response = client.get(reverse("accounts:settings") + "?tab=gmail")

    assert response.status_code == 200
    content = response.content.decode()
    assert "🟢" in content
    assert "Gmail" in content
    assert "Connected" in content
    assert "cannot be disconnected separately" in content
    assert "used to register and sign in to JobApply" in content
    assert "Open Gmail Assistant" not in content
    assert "Open Gmail statistics" not in content
    assert "refresh_token" not in content
    assert "access_token" not in content


def test_account_deletion_removes_the_current_users_data_and_logs_them_out(client, account):
    user, _profile = account
    user_id = user.pk
    application = JobApplication.objects.create(user=user, company="Example GmbH", title="Developer")
    client.force_login(user)

    account_page = client.get(reverse("accounts:settings") + "?tab=account")
    assert account_page.status_code == 200
    assert "Delete my account permanently" in account_page.content.decode()
    assert "This cannot be undone" in account_page.content.decode()

    response = client.post(reverse("accounts:delete_account"))

    assert response.status_code == 302
    assert response.url == reverse("landing")
    assert not get_user_model().objects.filter(pk=user_id).exists()
    assert not JobApplication.objects.filter(pk=application.pk).exists()
    assert client.get(reverse("accounts:settings")).status_code == 302


def test_account_deletion_rejects_get_requests(client, account):
    user, _profile = account
    client.force_login(user)

    response = client.get(reverse("accounts:delete_account"))

    assert response.status_code == 405
