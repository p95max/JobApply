from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gmail_assistant", "0005_gmailassistantsettings_atomic_ai_quota"),
    ]

    operations = [
        migrations.AlterField(
            model_name="gmailanalysis",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("application_confirmation_required", "Application confirmation required"),
                    ("application_draft_reminder", "Application draft reminder"),
                    ("application_sent", "Application sent"),
                    ("application_received", "Application received"),
                    ("general_update", "General update"),
                    ("screening", "Screening"),
                    ("documents_requested", "Documents requested"),
                    ("interview_invitation", "Interview invitation"),
                    ("interview_rescheduled", "Interview rescheduled"),
                    ("interview_cancelled", "Interview cancelled"),
                    ("offer", "Offer"),
                    ("rejection", "Rejection"),
                    ("withdrawal_confirmation", "Withdrawal confirmation"),
                    ("noise", "Noise"),
                    ("unknown", "Unknown"),
                ],
                default="unknown",
                max_length=48,
            ),
        ),
    ]
