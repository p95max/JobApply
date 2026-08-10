from django.db import migrations


def encrypt_existing_social_tokens(apps, schema_editor):
    from apps.security.oauth_tokens import encrypt_oauth_token

    SocialToken = apps.get_model("socialaccount", "SocialToken")
    for token in SocialToken.objects.all().only("id", "token", "token_secret").iterator(chunk_size=200):
        encrypted_token = encrypt_oauth_token(token.token)
        encrypted_secret = encrypt_oauth_token(token.token_secret)
        if encrypted_token != token.token or encrypted_secret != token.token_secret:
            SocialToken.objects.filter(pk=token.pk).update(
                token=encrypted_token,
                token_secret=encrypted_secret,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_useroperationquota"),
        ("socialaccount", "0001_initial"),
    ]

    operations = [migrations.RunPython(encrypt_existing_social_tokens, migrations.RunPython.noop)]
