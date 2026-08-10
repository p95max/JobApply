# Generated manually for per-user Gmail sync abuse controls.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gmail_stats", "0004_move_assistant_models_to_gmail_assistant"),
    ]

    operations = [
        migrations.AddField(
            model_name="gmailsyncstate",
            name="last_manual_sync_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="gmailsyncstate",
            name="sync_lock_token",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="gmailsyncstate",
            name="sync_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
