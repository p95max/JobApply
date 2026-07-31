# Generated manually for Gmail Assistant data models.

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0005_alter_jobapplication_options_and_more"),
        ("gmail_stats", "0002_gmailmessage_sync_hardening"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="GmailAnalysis",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("application_confirmation_required", "Application confirmation required"), ("application_sent", "Application sent"), ("application_received", "Application received"), ("general_update", "General update"), ("screening", "Screening"), ("documents_requested", "Documents requested"), ("interview_invitation", "Interview invitation"), ("interview_rescheduled", "Interview rescheduled"), ("interview_cancelled", "Interview cancelled"), ("offer", "Offer"), ("rejection", "Rejection"), ("withdrawal_confirmation", "Withdrawal confirmation"), ("noise", "Noise"), ("unknown", "Unknown")], default="unknown", max_length=48)),
                ("is_job_related", models.BooleanField(default=False)),
                ("classifier", models.CharField(choices=[("rule", "Rule"), ("ai", "AI"), ("rule_ai", "Rule and AI")], default="rule", max_length=16)),
                ("confidence", models.PositiveSmallIntegerField(default=0)),
                ("extracted_data", models.JSONField(default=dict)),
                ("proposed_status", models.CharField(blank=True, choices=[("applied", "Applied"), ("screen", "HR Screen"), ("replied", "Recruiter replied"), ("interview", "Interview"), ("offer", "Offer"), ("rejected", "Rejected"), ("archived", "Archived")], max_length=20, null=True)),
                ("model_name", models.CharField(blank=True, max_length=100)),
                ("prompt_version", models.CharField(default="v1", max_length=32)),
                ("schema_version", models.CharField(default="v1", max_length=32)),
                ("analyzed_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("message", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="analysis", to="gmail_stats.gmailmessage")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="gmail_analyses", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="GmailAssistantSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ai_enabled", models.BooleanField(default=False)),
                ("ai_consent_at", models.DateTimeField(blank=True, null=True)),
                ("last_successful_run_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="gmail_assistant_settings", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name="gmailmessage",
            name="application",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="gmail_messages", to="applications.jobapplication"),
        ),
        migrations.AddField(
            model_name="gmailmessage",
            name="content_hash",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="gmailmessage",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="gmailmessage",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="gmailmessage",
            name="processing_status",
            field=models.CharField(choices=[("new", "New"), ("parsed", "Parsed"), ("analyzed", "Analyzed"), ("proposal_created", "Proposal created"), ("ignored", "Ignored"), ("failed", "Failed")], db_index=True, default="new", max_length=16),
        ),
        migrations.AddConstraint(
            model_name="gmailanalysis",
            constraint=models.UniqueConstraint(fields=("user", "message"), name="unique_gmail_analysis_per_user_message"),
        ),
        migrations.AddConstraint(
            model_name="gmailanalysis",
            constraint=models.CheckConstraint(condition=models.Q(("confidence__lte", 100)), name="gmail_analysis_confidence_lte_100"),
        ),
        migrations.CreateModel(
            name="ApplicationUpdateProposal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("proposal_type", models.CharField(choices=[("create_application", "Create application"), ("update_application", "Update application"), ("create_interview", "Create interview"), ("update_interview", "Update interview"), ("action_required", "Action required")], max_length=32)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("accepted", "Accepted"), ("rejected", "Rejected"), ("ignored", "Ignored")], db_index=True, default="pending", max_length=16)),
                ("match_score", models.PositiveSmallIntegerField(default=0)),
                ("match_method", models.CharField(blank=True, max_length=100)),
                ("changes", models.JSONField(default=dict)),
                ("review_note", models.TextField(blank=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("analysis", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="proposals", to="gmail_stats.gmailanalysis")),
                ("application", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="update_proposals", to="applications.jobapplication")),
                ("message", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="proposals", to="gmail_stats.gmailmessage")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="application_update_proposals", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="applicationupdateproposal",
            constraint=models.UniqueConstraint(condition=models.Q(("status", "pending")), fields=("message", "analysis", "proposal_type"), name="unique_pending_proposal_per_analysis_type"),
        ),
        migrations.AddConstraint(
            model_name="applicationupdateproposal",
            constraint=models.CheckConstraint(condition=models.Q(("match_score__lte", 100)), name="application_proposal_match_score_lte_100"),
        ),
    ]
