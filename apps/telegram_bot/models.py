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
