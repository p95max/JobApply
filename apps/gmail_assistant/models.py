from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.applications.models import ApplicationStatus, JobApplication
from apps.gmail_stats.models import GmailMessage


class GmailEventType(models.TextChoices):
    APPLICATION_CONFIRMATION_REQUIRED = "application_confirmation_required", "Application confirmation required"
    APPLICATION_SENT = "application_sent", "Application sent"
    APPLICATION_RECEIVED = "application_received", "Application received"
    GENERAL_UPDATE = "general_update", "General update"
    SCREENING = "screening", "Screening"
    DOCUMENTS_REQUESTED = "documents_requested", "Documents requested"
    INTERVIEW_INVITATION = "interview_invitation", "Interview invitation"
    INTERVIEW_RESCHEDULED = "interview_rescheduled", "Interview rescheduled"
    INTERVIEW_CANCELLED = "interview_cancelled", "Interview cancelled"
    OFFER = "offer", "Offer"
    REJECTION = "rejection", "Rejection"
    WITHDRAWAL_CONFIRMATION = "withdrawal_confirmation", "Withdrawal confirmation"
    NOISE = "noise", "Noise"
    UNKNOWN = "unknown", "Unknown"


class AnalysisClassifier(models.TextChoices):
    RULE = "rule", "Rule"
    AI = "ai", "AI"
    RULE_AI = "rule_ai", "Rule and AI"


class ProposalType(models.TextChoices):
    CREATE_APPLICATION = "create_application", "Create application"
    UPDATE_APPLICATION = "update_application", "Update application"
    CREATE_INTERVIEW = "create_interview", "Create interview"
    UPDATE_INTERVIEW = "update_interview", "Update interview"
    ACTION_REQUIRED = "action_required", "Action required"


class ProposalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    IGNORED = "ignored", "Ignored"


class GmailAnalysis(models.Model):
    """A structured analysis result for one cached Gmail message."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="gmail_analyses")
    message = models.OneToOneField(GmailMessage, on_delete=models.CASCADE, related_name="analysis")
    event_type = models.CharField(max_length=48, choices=GmailEventType.choices, default=GmailEventType.UNKNOWN)
    is_job_related = models.BooleanField(default=False)
    classifier = models.CharField(max_length=16, choices=AnalysisClassifier.choices, default=AnalysisClassifier.RULE)
    confidence = models.PositiveSmallIntegerField(default=0)
    extracted_data = models.JSONField(default=dict)
    proposed_status = models.CharField(max_length=20, choices=ApplicationStatus.choices, null=True, blank=True)
    model_name = models.CharField(max_length=100, blank=True)
    prompt_version = models.CharField(max_length=32, default="v1")
    schema_version = models.CharField(max_length=32, default="v1")
    analyzed_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "gmail_stats_gmailanalysis"
        constraints = [
            models.UniqueConstraint(fields=["user", "message"], name="unique_gmail_analysis_per_user_message"),
            models.CheckConstraint(condition=models.Q(confidence__lte=100), name="gmail_analysis_confidence_lte_100"),
        ]

    def clean(self):
        super().clean()
        if self.user_id and self.message_id and self.message.user_id != self.user_id:
            raise ValidationError(
                {"message": "The Gmail message must belong to the analysis user."}
            )


class ApplicationUpdateProposal(models.Model):
    """A user-reviewed application or interview update proposed from Gmail."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="application_update_proposals",
    )
    message = models.ForeignKey(GmailMessage, on_delete=models.CASCADE, related_name="proposals")
    analysis = models.ForeignKey(GmailAnalysis, on_delete=models.CASCADE, related_name="proposals")
    application = models.ForeignKey(
        JobApplication,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="update_proposals",
    )
    proposal_type = models.CharField(max_length=32, choices=ProposalType.choices)
    status = models.CharField(max_length=16, choices=ProposalStatus.choices, default=ProposalStatus.PENDING, db_index=True)
    match_score = models.PositiveSmallIntegerField(default=0)
    match_method = models.CharField(max_length=100, blank=True)
    changes = models.JSONField(default=dict)
    review_note = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "gmail_stats_applicationupdateproposal"
        constraints = [
            models.UniqueConstraint(
                fields=["message", "analysis", "proposal_type"],
                condition=models.Q(status=ProposalStatus.PENDING),
                name="unique_pending_proposal_per_analysis_type",
            ),
            models.CheckConstraint(
                condition=models.Q(match_score__lte=100),
                name="application_proposal_match_score_lte_100",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.user_id and self.message_id and self.message.user_id != self.user_id:
            errors["message"] = "The Gmail message must belong to the proposal user."
        if self.user_id and self.analysis_id and self.analysis.user_id != self.user_id:
            errors["analysis"] = "The Gmail analysis must belong to the proposal user."
        if self.message_id and self.analysis_id and self.analysis.message_id != self.message_id:
            errors["analysis"] = "The Gmail analysis must belong to the proposal message."
        if self.user_id and self.application_id and self.application.user_id != self.user_id:
            errors["application"] = "The application must belong to the proposal user."
        if errors:
            raise ValidationError(errors)


class GmailAssistantSettings(models.Model):
    """Per-user Gmail Assistant consent and execution metadata."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gmail_assistant_settings",
    )
    ai_enabled = models.BooleanField(default=False)
    ai_consent_at = models.DateTimeField(null=True, blank=True)
    auto_apply_enabled = models.BooleanField(default=False)
    auto_apply_consent_at = models.DateTimeField(null=True, blank=True)
    ai_daily_usage_reset_at = models.DateTimeField(null=True, blank=True)
    ai_daily_usage_date = models.DateField(null=True, blank=True)
    ai_daily_usage_count = models.PositiveIntegerField(default=0)
    last_successful_run_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "gmail_stats_gmailassistantsettings"
