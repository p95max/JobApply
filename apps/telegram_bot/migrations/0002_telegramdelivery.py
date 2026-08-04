from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("telegram_bot", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="TelegramDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_key", models.CharField(max_length=180, unique=True)),
                ("event_type", models.CharField(max_length=64)),
                ("chat_id", models.BigIntegerField()),
                ("message_id", models.BigIntegerField(blank=True, null=True)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")], default="pending", max_length=16)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("error", models.CharField(blank=True, max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ("-created_at",)},
        ),
    ]
