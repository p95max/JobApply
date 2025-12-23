from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.applications.models import JobApplication


class InterviewStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    DONE = "done", "Done"
    CANCELED = "canceled", "Canceled"


class InterviewEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE)

    status = models.CharField(
        max_length=16,
        choices=InterviewStatus.choices,
        default=InterviewStatus.SCHEDULED,
    )

    starts_at = models.DateTimeField()
    location = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if not self.starts_at:
            return

    def __str__(self) -> str:
        return f"Interview: {self.application} @ {self.starts_at}"
