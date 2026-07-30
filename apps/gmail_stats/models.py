from __future__ import annotations

from django.conf import settings
from django.db import models


class GmailDirection(models.TextChoices):
    INBOUND = "inbound", "Inbound"
    OUTBOUND = "outbound", "Outbound"
    UNKNOWN = "unknown", "Unknown"


class GmailProcessingStatus(models.TextChoices):
    NEW = "new", "New"
    FAILED = "failed", "Failed"


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

    message_id = models.CharField(max_length=255)
    thread_id = models.CharField(max_length=255, db_index=True)

    direction = models.CharField(
        max_length=16,
        choices=GmailDirection.choices,
        default=GmailDirection.UNKNOWN,
        db_index=True,
    )
    received_at = models.DateTimeField(db_index=True)
    from_name = models.CharField(max_length=255, blank=True)
    from_email = models.EmailField(blank=True)
    to_emails = models.JSONField(default=list)
    subject = models.CharField(max_length=500, blank=True)
    snippet = models.TextField(blank=True)
    processing_status = models.CharField(
        max_length=16,
        choices=GmailProcessingStatus.choices,
        default=GmailProcessingStatus.NEW,
        db_index=True,
    )
    processing_error = models.TextField(blank=True)

    detected_type = models.CharField(max_length=32, choices=TYPES, default=TYPE_UNKNOWN, db_index=True)
    confidence = models.PositiveSmallIntegerField(default=0)
    is_user_verified = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["user", "received_at"]),
            models.Index(fields=["user", "detected_type"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "message_id"],
                name="unique_gmail_message_per_user",
            )
        ]


    def __str__(self) -> str:
        return f"GmailMessage({self.message_id}, {self.detected_type})"
