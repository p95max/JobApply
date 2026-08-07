from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("telegram_bot", "0004_telegramdeployrequest")]

    operations = [
        migrations.RenameIndex(
            model_name="telegramdeployrequest",
            old_name="telegram_bo_telegram_5b5bd0_idx",
            new_name="tg_deploy_usr_chat_status_idx",
        )
    ]
