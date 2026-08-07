from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gmail_assistant", "0002_openaitokenusage")]

    operations = [
        migrations.AddField(
            model_name="gmailassistantsettings",
            name="auto_apply_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="gmailassistantsettings",
            name="auto_apply_consent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
