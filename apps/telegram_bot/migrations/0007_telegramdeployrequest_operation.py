from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("telegram_bot", "0006_telegramdeployrequest_target_description"),
    ]

    operations = [
        migrations.AddField(
            model_name="telegramdeployrequest",
            name="operation",
            field=models.CharField(
                choices=[("deploy", "Deploy latest"), ("rollback", "Rollback")],
                default="deploy",
                max_length=16,
            ),
        ),
    ]
