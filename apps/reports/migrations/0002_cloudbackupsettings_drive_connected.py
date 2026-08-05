from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="cloudbackupsettings",
            name="drive_connected",
            field=models.BooleanField(default=False),
        ),
        migrations.AddIndex(
            model_name="cloudbackupsettings",
            index=models.Index(fields=["drive_connected"], name="reports_clo_drive_c_56d45a_idx"),
        ),
    ]
