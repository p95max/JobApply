from __future__ import annotations

from django.conf import settings
from django.db import models


class CloudBackupSettings(models.Model):
    """
    Per-user settings for Google Drive auto backups.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cloud_backup")
    enabled = models.BooleanField(default=False)
    last_run_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["enabled"]),
            models.Index(fields=["last_run_at"]),
        ]

    def __str__(self) -> str:
        return f"CloudBackupSettings(user_id={self.user_id}, enabled={self.enabled})"
