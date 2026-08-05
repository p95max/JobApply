from __future__ import annotations

from django.conf import settings
from django.db import models


class CloudBackupSettings(models.Model):
    """Per-user settings for optional Google Drive backups."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cloud_backup",
    )
    drive_connected = models.BooleanField(default=False)
    enabled = models.BooleanField(default=False)
    last_run_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["drive_connected"]),
            models.Index(fields=["enabled"]),
            models.Index(fields=["last_run_at"]),
        ]

    def __str__(self) -> str:
        return (
            f"CloudBackupSettings(user_id={self.user_id}, "
            f"drive_connected={self.drive_connected}, enabled={self.enabled})"
        )
