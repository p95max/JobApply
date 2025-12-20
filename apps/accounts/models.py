from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    google_data_access_consent = models.BooleanField(default=False)
    consent_accepted_at = models.DateTimeField(null=True, blank=True)

    def accept_consent(self) -> None:
        self.google_data_access_consent = True
        self.consent_accepted_at = timezone.now()
        self.save(update_fields=["google_data_access_consent", "consent_accepted_at"])
