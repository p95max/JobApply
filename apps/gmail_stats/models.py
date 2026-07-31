from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.applications.models import ApplicationStatus, JobApplication


class GmailDirection(models.TextChoices):
    INBOUND = "inbound", "Inbound"
    OUTBOUND = "outbound", "Outbound"
    UNKNOWN = "unknown", "Unknown"


class GmailProcessingStatus(models.TextChoices):
    NEW = "new", "New"
    PARSED = "parsed", "Parsed"
    ANALYZED = "analyzed", "Analyzed"
    PROPOSAL_CREATED = "proposal_created", "Proposal created"
    IGNORED = "ignored", "Ignored"
    FAILED = "failed", "Failed"


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
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    application = models.ForeignKey(
        JobApplication,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="gmail_messages",
    )

    detected_type = models.CharField(max_length=32, choices=TYPES, default=TYPE_UNKNOWN, db_index=True)
    confidence = models.PositiveSmallIntegerField(default=0)
    is_user_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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


class GmailAnalysis(models.Model):
    """Stores a structured analysis result for one Gmail message."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gmail_analyses",
    )
    message = models.OneToOneField(
        GmailMessage,
        on_delete=models.CASCADE,
        related_name="analysis",
    )
    event_type = models.CharField(
        max_length=48,
        choices=GmailEventType.choices,
        default=GmailEventType.UNKNOWN,
    )
    is_job_related = models.BooleanField(default=False)
    classifier = models.CharField(
        max_length=16,
        choices=AnalysisClassifier.choices,
        default=AnalysisClassifier.RULE,
    )
    confidence = models.PositiveSmallIntegerField(default=0)
    extracted_data = models.JSONField(default=dict)
    proposed_status = models.CharField(
        max_length=20,
        choices=ApplicationStatus.choices,
        null=True,
        blank=True,
    )
    model_name = models.CharField(max_length=100, blank=True)
    prompt_version = models.CharField(max_length=32, default="v1")
    schema_version = models.CharField(max_length=32, default="v1")
    analyzed_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "message"],
                name="unique_gmail_analysis_per_user_message",
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__lte=100),
                name="gmail_analysis_confidence_lte_100",
            ),
        ]


class ApplicationUpdateProposal(models.Model):
    """Stores a user-reviewed proposed change derived from a Gmail analysis."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="application_update_proposals",
    )
    message = models.ForeignKey(
        GmailMessage,
        on_delete=models.CASCADE,
        related_name="proposals",
    )
    analysis = models.ForeignKey(
        GmailAnalysis,
        on_delete=models.CASCADE,
        related_name="proposals",
    )
    application = models.ForeignKey(
        JobApplication,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="update_proposals",
    )
    proposal_type = models.CharField(max_length=32, choices=ProposalType.choices)
    status = models.CharField(
        max_length=16,
        choices=ProposalStatus.choices,
        default=ProposalStatus.PENDING,
        db_index=True,
    )
    match_score = models.PositiveSmallIntegerField(default=0)
    match_method = models.CharField(max_length=100, blank=True)
    changes = models.JSONField(default=dict)
    review_note = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
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


class GmailAssistantSettings(models.Model):
    """Stores per-user Gmail Assistant preferences and run metadata."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gmail_assistant_settings",
    )
    ai_enabled = models.BooleanField(default=False)
    ai_consent_at = models.DateTimeField(null=True, blank=True)
    last_successful_run_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
