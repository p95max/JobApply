from __future__ import annotations

import pytest
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken

from apps.security.oauth_tokens import decrypt_oauth_token


@pytest.mark.django_db
def test_social_tokens_are_encrypted_at_rest(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    account = SocialAccount.objects.create(user=user, provider="google", uid="google-user")
    token = SocialToken.objects.create(
        account=account,
        token="plain-access-token",
        token_secret="plain-refresh-token",
    )
    token.refresh_from_db()

    assert token.token.startswith("enc:v1:")
    assert token.token_secret.startswith("enc:v1:")
    assert "plain-access-token" not in token.token
    assert "plain-refresh-token" not in token.token_secret
    assert decrypt_oauth_token(token.token) == "plain-access-token"
    assert decrypt_oauth_token(token.token_secret) == "plain-refresh-token"


@pytest.mark.django_db
def test_legacy_plaintext_tokens_remain_readable_during_rollout(django_user_model):
    user = django_user_model.objects.create_user("user", email="user@example.com")
    account = SocialAccount.objects.create(user=user, provider="google", uid="legacy-google-user")
    token = SocialToken.objects.create(account=account, token="initial", token_secret="initial")
    # QuerySet.update bypasses the save signal and simulates a pre-migration row.
    SocialToken.objects.filter(pk=token.pk).update(token="legacy-access", token_secret="legacy-refresh")
    token.refresh_from_db()

    assert decrypt_oauth_token(token.token) == "legacy-access"
    assert decrypt_oauth_token(token.token_secret) == "legacy-refresh"


@pytest.mark.django_db
def test_gmail_credentials_decrypt_stored_social_tokens(django_user_model):
    from apps.gmail_stats.services.credentials import get_google_credentials_for_user

    user = django_user_model.objects.create_user("user", email="user@example.com")
    app = SocialApp.objects.create(
        provider="google",
        name="Google",
        client_id="client-id",
        secret="client-secret",
    )
    account = SocialAccount.objects.create(user=user, provider="google", uid="credential-google-user")
    SocialToken.objects.create(
        account=account,
        app=app,
        token="access-token",
        token_secret="refresh-token",
    )

    credentials = get_google_credentials_for_user(user)

    assert credentials is not None
    assert credentials.token == "access-token"
    assert credentials.refresh_token == "refresh-token"
