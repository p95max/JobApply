# Generated manually for Gmail sync hardening.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gmail_stats", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="gmailmessage",
            name="message_id",
            field=models.CharField(max_length=255),
        ),
        migrations.AddField(
            model_name="gmailmessage",
            name="direction",
            field=models.CharField(
                choices=[("inbound", "Inbound"), ("outbound", "Outbound"), ("unknown", "Unknown")],
                db_index=True,
                default="unknown",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="gmailmessage",
            name="from_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="gmailmessage",
            name="to_emails",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="gmailmessage",
            name="processing_status",
            field=models.CharField(
                choices=[("new", "New"), ("failed", "Failed")],
                db_index=True,
                default="new",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="gmailmessage",
            name="processing_error",
            field=models.TextField(blank=True),
        ),
        migrations.AddConstraint(
            model_name="gmailmessage",
            constraint=models.UniqueConstraint(
                fields=("user", "message_id"),
                name="unique_gmail_message_per_user",
            ),
        ),
    ]
