from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("telegram_bot", "0003_telegramcommandaudit")]

    operations = [
        migrations.CreateModel(
            name="TelegramDeployRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("telegram_user_id", models.BigIntegerField()),
                ("chat_id", models.BigIntegerField()),
                ("current_commit", models.CharField(max_length=64)),
                ("target_commit", models.CharField(max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending confirmation"),
                            ("queued", "Queued"),
                            ("canceled", "Canceled"),
                            ("expired", "Expired"),
                            ("busy", "Queue busy"),
                            ("failed", "Failed to queue"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("expires_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddIndex(
            model_name="telegramdeployrequest",
            index=models.Index(
                fields=["telegram_user_id", "chat_id", "status"],
                name="telegram_bo_telegram_5b5bd0_idx",
            ),
        ),
    ]
