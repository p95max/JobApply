from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("telegram_bot", "0002_telegramdelivery")]

    operations = [
        migrations.CreateModel(
            name="TelegramCommandAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user_id", models.BigIntegerField()),
                ("chat_id", models.BigIntegerField()),
                ("command", models.CharField(max_length=32)),
                ("result", models.CharField(max_length=32)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddIndex(
            model_name="telegramcommandaudit",
            index=models.Index(fields=["user_id", "chat_id", "created_at"], name="telegram_bo_user_id_5a738f_idx"),
        ),
    ]
