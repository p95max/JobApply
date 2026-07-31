"""Remove Assistant models from gmail_stats migration state only.

The matching tables are adopted by gmail_assistant.0001 without database DDL.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("gmail_assistant", "0001_adopt_legacy_models"),
        ("gmail_stats", "0003_gmail_assistant_models"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name="ApplicationUpdateProposal"),
                migrations.DeleteModel(name="GmailAnalysis"),
                migrations.DeleteModel(name="GmailAssistantSettings"),
            ],
        )
    ]
