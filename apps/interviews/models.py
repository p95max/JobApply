from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.applications.models import ApplicationStatus, JobApplication


class InterviewEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE)

    starts_at = models.DateTimeField()
    location = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()

        if not self.starts_at or not self.ends_at:
            return

        if self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": _("End time must be after start time.")})

    def __str__(self) -> str:
        return f"Interview: {self.application} @ {self.starts_at}"
