from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="WorkerHeartbeat",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("worker_name", models.CharField(max_length=64, unique=True)),
                ("expected_interval_seconds", models.PositiveIntegerField(default=300)),
                ("last_seen_at", models.DateTimeField()),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_message", models.CharField(blank=True, max_length=120)),
            ],
            options={"ordering": ("worker_name",)},
        ),
    ]
