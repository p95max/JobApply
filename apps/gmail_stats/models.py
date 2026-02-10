from __future__ import annotations

from django.conf import settings
from django.db import models


class GmailSyncState(models.Model):
    """Tracks last sync moment for incremental runs."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"GmailSyncState(user_id={self.user_id})"


class GmailMessage(models.Model):
    """A cached Gmail message metadata used for statistics."""

    TYPE_UNKNOWN = "unknown"
    TYPE_RESPONSE = "response"
    TYPE_REJECTION = "rejection"
    TYPE_INVITE = "invite"
    TYPE_AUTO_ACK = "auto_ack"
    TYPE_NOISE = "noise"

    TYPES = [
        (TYPE_UNKNOWN, "Unknown"),
        (TYPE_RESPONSE, "Response"),
        (TYPE_REJECTION, "Rejection"),
        (TYPE_INVITE, "Invite"),
        (TYPE_AUTO_ACK, "Auto acknowledgment"),
        (TYPE_NOISE, "Noise"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    message_id = models.CharField(max_length=255, unique=True)
    thread_id = models.CharField(max_length=255, db_index=True)

    received_at = models.DateTimeField(db_index=True)
    from_email = models.EmailField(blank=True)
    subject = models.CharField(max_length=500, blank=True)
    snippet = models.TextField(blank=True)

    detected_type = models.CharField(max_length=32, choices=TYPES, default=TYPE_UNKNOWN, db_index=True)
    confidence = models.PositiveSmallIntegerField(default=0)
    is_user_verified = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["user", "received_at"]),
            models.Index(fields=["user", "detected_type"]),
        ]

    def __str__(self) -> str:
        return f"GmailMessage({self.message_id}, {self.detected_type})"
