from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class ApplicationStatus(models.TextChoices):
    APPLIED = "applied", _("Applied")
    SCREEN = "screen", _("HR Screen")
    REPLIED = "replied", _("Recruiter replied")
    INTERVIEW = "interview", _("Interview")
    OFFER = "offer", _("Offer")
    REJECTED = "rejected", _("Rejected")
    ARCHIVED = "archived", _("Archived")

class ApplicationSource(models.TextChoices):
    STEPSTONE = "stepstone", _("StepStone")
    LINKEDIN = "linkedin", _("LinkedIn")
    INDEED = "indeed", _("Indeed")
    XING = "xing", _("Xing")
    GLASSDOOR = "glassdoor", _("Glassdoor")
    ARBEITSAGENTUR = "arbeitsagentur", _("Arbeitsagentur")
    COMPANY_SITE = "company", _("Company website")
    RECRUITER = "recruiter", _("Recruiter")
    REFERRAL = "referral", _("Referral")
    OTHER = "other", _("Other")




class JobApplication(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    title = models.CharField(max_length=200)
    company = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)

    source = models.CharField(
        max_length=50,
        choices=ApplicationSource.choices,
        blank=True,
        verbose_name=_("Source"),
    )

    status = models.CharField(max_length=20, choices=ApplicationStatus.choices, default=ApplicationStatus.APPLIED)

    applied_at = models.DateTimeField(default=timezone.now)
    recruiter_reply_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        verbose_name = _("Job application")
        verbose_name_plural = _("Job applications")

    def __str__(self) -> str:
        return f"{self.company} — {self.title}"
