from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    is_demo_user = models.BooleanField(default=False)
    google_data_access_consent = models.BooleanField(default=False)
    consent_accepted_at = models.DateTimeField(null=True, blank=True)
    telegram_user_id = models.BigIntegerField(null=True, blank=True, unique=True)
    telegram_chat_id = models.BigIntegerField(null=True, blank=True, unique=True)
    telegram_linked_at = models.DateTimeField(null=True, blank=True)
    telegram_link_token_hash = models.CharField(max_length=64, blank=True)
    telegram_link_token_expires_at = models.DateTimeField(null=True, blank=True)

    def accept_consent(self) -> None:
        self.google_data_access_consent = True
        self.consent_accepted_at = timezone.now()
        self.save(update_fields=["google_data_access_consent", "consent_accepted_at"])

    def create_telegram_link_token(self, *, lifetime_minutes: int = 15) -> str:
        token = secrets.token_urlsafe(24)
        self.telegram_link_token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self.telegram_link_token_expires_at = timezone.now() + timedelta(minutes=lifetime_minutes)
        self.save(update_fields=["telegram_link_token_hash", "telegram_link_token_expires_at"])
        return token

    def clear_telegram_link(self) -> None:
        self.telegram_user_id = None
        self.telegram_chat_id = None
        self.telegram_linked_at = None
        self.telegram_link_token_hash = ""
        self.telegram_link_token_expires_at = None
        self.save(
            update_fields=[
                "telegram_user_id",
                "telegram_chat_id",
                "telegram_linked_at",
                "telegram_link_token_hash",
                "telegram_link_token_expires_at",
            ]
        )
