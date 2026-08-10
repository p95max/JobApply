# Generated manually for Telegram connection token rate limiting.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_userprofile_is_demo_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="telegram_link_token_issued_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
