from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gmail_assistant", "0003_gmailassistantsettings_auto_apply")]

    operations = [
        migrations.AddField(
            model_name="gmailassistantsettings",
            name="ai_daily_usage_reset_at",
            field=models.DateTimeField(blank=True, null=True),
        )
    ]
