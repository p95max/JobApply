from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

from apps.gmail_stats.services.gmail_client import GmailClient
from apps.gmail_stats.services.sync import sync_gmail_messages_for_user
from datetime import timedelta
from typing import Optional

import requests
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.utils import timezone
from google.oauth2.credentials import Credentials

# TODO: implement get_google_credentials_for_user(user)


class Command(BaseCommand):
    help = "Sync Gmail messages for statistics (responses/rejections/invites)."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--days", type=int, default=180)
        parser.add_argument("--max", type=int, default=500)

    def handle(self, *args, **opts):
        user_id = opts["user_id"]
        days = opts["days"]
        max_results_each = opts["max"]

        User = get_user_model()
        user = User.objects.filter(id=user_id).first()
        if not user:
            raise CommandError(f"User id={user_id} not found")

        credentials = get_google_credentials_for_user(user)  # you implement
        if not credentials:
            raise CommandError("No Google credentials for this user (missing Gmail scope?)")

        gmail_client = GmailClient(credentials)
        res = sync_gmail_messages_for_user(user=user, gmail_client=gmail_client, days=days, max_results_each=max_results_each)

        self.stdout.write(self.style.SUCCESS(f"OK: {res}"))

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def get_google_credentials_for_user(user) -> Optional[Credentials]:
    """
    Build google-auth Credentials for the given user from django-allauth tables.

    Works with:
      - SocialAccount(provider="google")
      - SocialToken.token         -> access_token
      - SocialToken.token_secret  -> refresh_token (typical allauth convention)
      - SocialToken.expires_at    -> access_token expiry
      - SocialApp(client_id/secret)

    Refreshes access token if expired (requires refresh_token).
    Returns None if user has no Google account/token or refresh is impossible.
    """
    account = (
        SocialAccount.objects
        .filter(user=user, provider="google")
        .order_by("-id")
        .first()
    )
    if not account:
        return None

    token_obj = (
        SocialToken.objects
        .select_related("app")
        .filter(account=account)
        .order_by("-id")
        .first()
    )
    if not token_obj:
        return None

    app = token_obj.app or (
        SocialApp.objects.filter(provider="google").order_by("-id").first()
    )
    if not app:
        return None

    access_token = (token_obj.token or "").strip()
    refresh_token = (token_obj.token_secret or "").strip()
    expires_at = token_obj.expires_at

    if not access_token:
        return None

    if _is_expired(expires_at):
        if not refresh_token:
            return None

        new_access_token, new_expires_at = _refresh_google_access_token(
            client_id=app.client_id,
            client_secret=app.secret,
            refresh_token=refresh_token,
        )

        token_obj.token = new_access_token
        token_obj.expires_at = new_expires_at
        token_obj.save(update_fields=["token", "expires_at"])

        access_token = new_access_token
        expires_at = new_expires_at

    return Credentials(
        token=access_token,
        refresh_token=refresh_token or None,
        token_uri=GOOGLE_TOKEN_URL,
        client_id=app.client_id,
        client_secret=app.secret,
        scopes=None,
    )


def _is_expired(expires_at) -> bool:
    if not expires_at:
        return False
    return expires_at <= timezone.now() + timedelta(seconds=30)


def _refresh_google_access_token(*, client_id: str, client_secret: str, refresh_token: str) -> tuple[str, timezone.datetime]:
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
    if resp.status_code != 200:
        raise RuntimeError(f"Google token refresh failed: {resp.status_code} {resp.text}")

    data = resp.json()
    access_token = data["access_token"]
    expires_in = int(data.get("expires_in", 3600))
    expires_at = timezone.now() + timedelta(seconds=expires_in)
    return access_token, expires_at

