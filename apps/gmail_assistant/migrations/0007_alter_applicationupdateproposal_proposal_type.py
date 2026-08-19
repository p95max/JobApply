from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gmail_assistant", "0006_telegramdeployrequest_target_description") if False else ("gmail_assistant", "0006_gmailanalysis_application_draft_reminder"),
    ]

    operations = [
        migrations.AlterField(
            model_name="applicationupdateproposal",
            name="proposal_type",
            field=models.CharField(
                choices=[
                    ("create_application", "Create application"),
                    ("update_application", "Update application"),
                    ("create_interview", "Create interview"),
                    ("update_interview", "Update interview"),
                    ("action_required", "Action required"),
                    ("activity", "Gmail activity"),
                ],
                max_length=32,
            ),
        ),
    ]
