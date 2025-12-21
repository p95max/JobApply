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
    ends_at = models.DateTimeField()
    location = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self) -> None:
        if self.application.status != ApplicationStatus.INTERVIEW:
            raise ValidationError("InterviewEvent can be linked only to applications with status=interview.")
        if self.ends_at <= self.starts_at:
            raise ValidationError("ends_at must be greater than starts_at.")
        if self.starts_at < timezone.now() - timezone.timedelta(days=365):
            raise ValidationError("starts_at looks invalid (too far in the past).")

    def __str__(self) -> str:
        return f"Interview: {self.application} @ {self.starts_at}"
