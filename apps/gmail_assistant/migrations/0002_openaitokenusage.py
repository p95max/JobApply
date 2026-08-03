import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gmail_assistant", "0001_adopt_legacy_models"),
        ("gmail_stats", "0004_move_assistant_models_to_gmail_assistant"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OpenAITokenUsage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("model_name", models.CharField(max_length=100)),
                ("input_tokens", models.PositiveIntegerField(default=0)),
                ("output_tokens", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "message",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="openai_token_usage",
                        to="gmail_stats.gmailmessage",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="gmail_openai_token_usage",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "gmail_assistant_openaitokenusage",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="openaitokenusage",
            constraint=models.UniqueConstraint(
                fields=("message", "model_name"),
                name="unique_openai_usage_per_message_model",
            ),
        ),
    ]
