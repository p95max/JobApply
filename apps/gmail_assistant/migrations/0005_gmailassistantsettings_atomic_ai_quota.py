# Generated manually for atomic per-user AI quota reservation.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gmail_assistant", "0004_gmailassistantsettings_ai_daily_usage_reset"),
    ]

    operations = [
        migrations.AddField(
            model_name="gmailassistantsettings",
            name="ai_daily_usage_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="gmailassistantsettings",
            name="ai_daily_usage_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
