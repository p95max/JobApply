from django.db import migrations


def restore_sent_create_action_history(apps, schema_editor):
    ApplicationUpdateProposal = apps.get_model("gmail_assistant", "ApplicationUpdateProposal")
    ApplicationUpdateProposal.objects.filter(
        proposal_type="activity",
        status="accepted",
        changes__application__operation="create",
    ).update(proposal_type="create_application")


class Migration(migrations.Migration):
    dependencies = [
        ("gmail_assistant", "0007_alter_applicationupdateproposal_proposal_type"),
    ]

    operations = [
        migrations.RunPython(restore_sent_create_action_history, migrations.RunPython.noop),
    ]
