# Generated manually for per-user expensive-operation limits.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_userprofile_telegram_link_token_issued_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserOperationQuota",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("operation", models.CharField(max_length=48)),
                ("usage_date", models.DateField()),
                ("count", models.PositiveIntegerField(default=0)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="useroperationquota",
            constraint=models.UniqueConstraint(
                fields=("user", "operation"),
                name="accounts_unique_user_operation_quota",
            ),
        ),
        migrations.AddIndex(
            model_name="useroperationquota",
            index=models.Index(fields=["operation", "usage_date"], name="accounts_us_operati_ef553c_idx"),
        ),
    ]
