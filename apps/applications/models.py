from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class ApplicationStatus(models.TextChoices):
    APPLIED = "applied", "Applied"
    REPLIED = "replied", "Recruiter replied"
    INTERVIEW = "interview", "Interview"
    OFFER = "offer", "Offer"
    REJECTED = "rejected", "Rejected"
    ARCHIVED = "archived", "Archived"


class JobApplication(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    title = models.CharField(max_length=200)
    company = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)
    source = models.CharField(max_length=100, blank=True)  
    status = models.CharField(max_length=20, choices=ApplicationStatus.choices, default=ApplicationStatus.APPLIED)

    applied_at = models.DateField(default=timezone.now)
    recruiter_reply_at = models.DateField(null=True, blank=True)

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]

    def __str__(self) -> str:
        return f"{self.company} — {self.title}"
