from __future__ import annotations

from django.db import models


class WorkerHeartbeat(models.Model):
    worker_name = models.CharField(max_length=64, unique=True)
    expected_interval_seconds = models.PositiveIntegerField(default=300)
    last_seen_at = models.DateTimeField()
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ("worker_name",)

    def __str__(self) -> str:
        return self.worker_name


class TelegramDeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"


class TelegramDelivery(models.Model):
    event_key = models.CharField(max_length=180, unique=True)
    event_type = models.CharField(max_length=64)
    chat_id = models.BigIntegerField()
    message_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=TelegramDeliveryStatus.choices,
        default=TelegramDeliveryStatus.PENDING,
    )
    attempts = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.event_key


class TelegramCommandAudit(models.Model):
    """A minimal, secret-free audit trail for Telegram actions."""

    user_id = models.BigIntegerField()
    chat_id = models.BigIntegerField()
    command = models.CharField(max_length=32)
    result = models.CharField(max_length=32)
    duration_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("user_id", "chat_id", "created_at"))]

    def __str__(self) -> str:
        return f"{self.command}: {self.result}"
