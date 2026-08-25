from __future__ import annotations

from importlib import import_module

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailAssistantSettings,
    GmailEventType,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_stats.models import GmailMessage, GmailProcessingStatus


def test_assistant_models_are_owned_by_the_dedicated_app_without_table_recreation():
    assert GmailAnalysis._meta.app_label == "gmail_assistant"
    assert ApplicationUpdateProposal._meta.app_label == "gmail_assistant"
    assert GmailAssistantSettings._meta.app_label == "gmail_assistant"
    assert GmailAnalysis._meta.db_table == "gmail_stats_gmailanalysis"
    assert ApplicationUpdateProposal._meta.db_table == "gmail_stats_applicationupdateproposal"
    assert GmailAssistantSettings._meta.db_table == "gmail_stats_gmailassistantsettings"


def test_assistant_adoption_migrations_are_state_only():
    adoption = import_module("apps.gmail_assistant.migrations.0001_adopt_legacy_models").Migration
    removal = import_module("apps.gmail_stats.migrations.0004_move_assistant_models_to_gmail_assistant").Migration

    assert adoption.operations[0].database_operations == []
    assert removal.operations[0].database_operations == []


@pytest.fixture
def gmail_message(db, django_user_model):
    user = django_user_model.objects.create_user("gmail-user", email="gmail-user@example.com")
    message = GmailMessage.objects.create(
        user=user,
        message_id="gmail-message-id",
        thread_id="gmail-thread-id",
        received_at=timezone.now(),
    )
    return user, message


@pytest.mark.django_db
def test_gmail_message_assistant_defaults(gmail_message):
    _, message = gmail_message

    assert message.to_emails == []
    assert message.content_hash == ""
    assert message.application is None
    assert message.processing_status == GmailProcessingStatus.NEW
    assert message.processing_error == ""
    assert message.created_at is not None
    assert message.updated_at is not None


@pytest.mark.django_db
def test_gmail_analysis_is_unique_per_message(gmail_message):
    user, message = gmail_message
    GmailAnalysis.objects.create(
        user=user,
        message=message,
        event_type=GmailEventType.APPLICATION_RECEIVED,
        is_job_related=True,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        GmailAnalysis.objects.create(user=user, message=message)


@pytest.mark.django_db
def test_gmail_assistant_settings_defaults_to_rule_only_mode(gmail_message):
    user, _ = gmail_message
    settings = GmailAssistantSettings.objects.create(user=user)

    assert settings.ai_enabled is False
    assert settings.ai_consent_at is None
    assert settings.last_successful_run_at is None
    assert settings.last_error_at is None
    assert settings.last_error_message == ""


@pytest.mark.django_db
def test_only_one_pending_proposal_per_analysis_type(gmail_message):
    user, message = gmail_message
    analysis = GmailAnalysis.objects.create(user=user, message=message)
    proposal_kwargs = {
        "user": user,
        "message": message,
        "analysis": analysis,
        "proposal_type": ProposalType.UPDATE_APPLICATION,
    }
    ApplicationUpdateProposal.objects.create(**proposal_kwargs)

    with pytest.raises(IntegrityError), transaction.atomic():
        ApplicationUpdateProposal.objects.create(**proposal_kwargs)

    ApplicationUpdateProposal.objects.create(
        **proposal_kwargs,
        status=ProposalStatus.ACCEPTED,
    )
