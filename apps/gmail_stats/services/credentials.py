from __future__ import annotations

from datetime import timedelta
from typing import Optional

import requests
from django.utils import timezone
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken

from google.oauth2.credentials import Credentials

from apps.security.oauth_tokens import OAuthTokenError, decrypt_oauth_token


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def get_google_credentials_for_user(user) -> Optional[Credentials]:
    """
    Build google-auth Credentials from django-allauth SocialToken.
    Refreshes access token if expired (requires refresh token).
    Returns None if Google account/token not found.
    """
    account = (
        SocialAccount.objects
        .filter(user=user, provider="google")
        .order_by("-id")
        .first()
    )
    if not account:
        return None

    token = (
        SocialToken.objects
        .select_related("app")
        .filter(account=account)
        .order_by("-id")
        .first()
    )
    if not token:
        return None

    app = token.app or SocialApp.objects.filter(provider="google").order_by("-id").first()
    if not app:
        return None



    try:
        access_token = decrypt_oauth_token(token.token)
        refresh_token = decrypt_oauth_token(token.token_secret)
    except OAuthTokenError:
        return None

    if not access_token:
        return None

    expires_at = token.expires_at

    if _is_expired(expires_at):
        if not refresh_token:
            return None

        new_access_token, new_expires_at = _refresh_google_access_token(
            client_id=app.client_id,
            client_secret=app.secret,
            refresh_token=refresh_token,
        )

        token.token = new_access_token
        token.expires_at = new_expires_at
        token.save(update_fields=["token", "expires_at"])

        access_token = new_access_token
        expires_at = new_expires_at

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token or None,
        token_uri=GOOGLE_TOKEN_URL,
        client_id=app.client_id,
        client_secret=app.secret,
        scopes=None,
    )

    return creds


def _is_expired(expires_at) -> bool:
    if not expires_at:
        return False

    return expires_at <= timezone.now() + timedelta(seconds=30)


def _refresh_google_access_token(*, client_id: str, client_secret: str, refresh_token: str) -> tuple[str, timezone.datetime]:
    try:
        resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
    except requests.RequestException as error:
        raise RuntimeError("Google token refresh request failed") from error
    if resp.status_code != 200:
        raise RuntimeError(f"Google token refresh failed (HTTP {resp.status_code})")

    try:
        data = resp.json()
        access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("Google token refresh returned an invalid response") from error
    expires_at = timezone.now() + timedelta(seconds=expires_in)

    return access_token, expires_at
