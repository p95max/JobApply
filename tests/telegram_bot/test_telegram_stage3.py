from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.gmail_assistant.models import ApplicationUpdateProposal, GmailAnalysis, ProposalStatus, ProposalType
from apps.gmail_stats.models import GmailMessage
from apps.telegram_bot.diagnostics import DoctorSnapshot, HealthSnapshot
from apps.telegram_bot.heartbeat import HeartbeatStatus
from apps.telegram_bot.handlers import handle_update
from apps.telegram_bot.models import TelegramCommandAudit
from apps.telegram_bot.texts import doctor_text


class FakeClient:
    def __init__(self):
        self.messages = []
        self.answers = []
        self.edits = []

    def send_message(self, chat_id, text, *, reply_markup=None):
        self.messages.append((chat_id, text, reply_markup))

    def answer_callback_query(self, callback_id, text):
        self.answers.append((callback_id, text))

    def edit_message_text(self, chat_id, message_id, text):
        self.edits.append((chat_id, message_id, text))


def config(**overrides):
    values = {
        "enabled": True,
        "token": "test-token",
        "default_chat_id": 100,
        "allowed_chat_ids": frozenset({100}),
        "allowed_user_ids": frozenset({200}),
        "owner_user_id": 200,
        "owner_email": "owner@example.com",
        "environment_label": "TEST",
        "notifications_enabled": False,
        "callback_ttl_seconds": 900,
        "rate_limit_count": 20,
        "rate_limit_window_seconds": 60,
    }
    values.update(overrides)
    from apps.telegram_bot.config import TelegramConfig

    return TelegramConfig(**values)


def callback_update(proposal_id: int, action: str = "accept", *, user_id: int = 200) -> dict:
    return {
        "callback_query": {
            "id": "callback-1",
            "data": f"proposal:{proposal_id}:{action}",
            "from": {"id": user_id},
            "message": {"message_id": 45, "chat": {"id": 100, "type": "private"}},
        }
    }


@pytest.fixture
def proposal(django_user_model):
    user = django_user_model.objects.create_user("owner", email="owner@example.com")
    message = GmailMessage.objects.create(
        user=user,
        message_id="telegram-stage-3",
        thread_id="telegram-stage-3",
        received_at=timezone.now(),
        subject="Application received",
    )
    analysis = GmailAnalysis.objects.create(user=user, message=message, is_job_related=True)
    return ApplicationUpdateProposal.objects.create(
        user=user,
        message=message,
        analysis=analysis,
        proposal_type=ProposalType.CREATE_APPLICATION,
        changes={
            "application": {
                "operation": "create",
                "title": "Developer",
                "company": "Example GmbH",
                "status": "applied",
                "applied_at": timezone.now().isoformat(),
            }
        },
    )


@pytest.mark.django_db
def test_callback_accepts_a_pending_proposal_and_edits_original_message(proposal):
    client = FakeClient()

    handle_update(callback_update(proposal.pk), client, config())

    proposal.refresh_from_db()
    assert proposal.status == ProposalStatus.ACCEPTED
    assert client.answers[0][0] == "callback-1"
    assert "accepted" in client.edits[0][2].lower()
    assert TelegramCommandAudit.objects.get().result == "accept"


@pytest.mark.django_db
def test_callback_rejects_repeat_and_expired_actions(proposal):
    client = FakeClient()
    proposal.created_at = timezone.now() - timedelta(minutes=16)
    proposal.save(update_fields=["created_at"])

    handle_update(callback_update(proposal.pk), client, config(callback_ttl_seconds=60))

    proposal.refresh_from_db()
    assert proposal.status == ProposalStatus.PENDING
    assert "expired" in client.answers[0][1].lower()

    proposal.status = ProposalStatus.REJECTED
    proposal.save(update_fields=["status"])
    handle_update(callback_update(proposal.pk, "reject"), client, config())
    assert "already reviewed" in client.answers[-1][1].lower()


@pytest.mark.django_db
def test_callback_is_owner_only_and_rate_limited(proposal):
    client = FakeClient()
    handle_update(callback_update(proposal.pk, user_id=201), client, config(allowed_user_ids=frozenset({200, 201})))
    assert "only to the bot owner" in client.answers[0][1]

    TelegramCommandAudit.objects.create(user_id=200, chat_id=100, command="help", result="ok")
    handle_update(callback_update(proposal.pk), client, config(rate_limit_count=1))
    assert "Too many requests" in client.answers[-1][1]


@pytest.mark.django_db
def test_client_help_hides_admin_commands_and_admin_menu_is_owner_only():
    client = FakeClient()
    owner = {"message": {"text": "/admin", "chat": {"id": 100, "type": "private"}, "from": {"id": 200}}}
    client_help = {"message": {"text": "/help", "chat": {"id": 100, "type": "private"}, "from": {"id": 201}}}
    client_admin = {"message": {"text": "/admin", "chat": {"id": 100, "type": "private"}, "from": {"id": 201}}}
    shared_config = config(allowed_user_ids=frozenset({200, 201}))

    handle_update(client_help, client, shared_config)
    handle_update(owner, client, shared_config)
    handle_update(client_admin, client, shared_config)

    assert "/deploy" not in client.messages[0][1]
    assert "/admin" not in client.messages[0][1]
    assert "TEST" not in client.messages[0][1]
    assert "/status" in client.messages[1][1]
    assert "/deploy" in client.messages[1][1]
    assert "only to the bot owner" in client.messages[2][1]


@pytest.mark.django_db
@pytest.mark.parametrize("command", ["/status", "/health", "/doctor", "/deploy"])
def test_client_cannot_run_administrative_commands(command):
    client = FakeClient()
    update = {"message": {"text": command, "chat": {"id": 100, "type": "private"}, "from": {"id": 201}}}

    handle_update(update, client, config(allowed_user_ids=frozenset({200, 201})))

    assert "only to the bot owner" in client.messages[0][1]


@pytest.mark.django_db
def test_gmail_command_uses_web_review_button_without_action_buttons(proposal):
    client = FakeClient()

    handle_update(
        {"message": {"text": "/gmail", "chat": {"id": 100, "type": "private"}, "from": {"id": 200}}},
        client,
        config(),
    )

    assert "Pending proposals: <b>1</b>" in client.messages[0][1]
    assert "href=" not in client.messages[0][1]
    assert client.messages[0][2] == {
        "inline_keyboard": [
            [
                {
                    "text": "📨 Open Gmail Assistant",
                    "url": "https://jobapply.p95max.dev/gmail_stats/gmail/assistant/",
                }
            ]
        ]
    }


@pytest.mark.django_db
def test_health_and_doctor_do_not_expose_configuration(monkeypatch, django_user_model):
    django_user_model.objects.create_user("owner", email="owner@example.com")
    client = FakeClient()
    health = HealthSnapshot(True, 512, (HeartbeatStatus("gmail_worker", None, False, ""),))
    doctor = DoctorSnapshot(health, "master", False, 0, (), (("jobapply-web.service", "active"),))
    monkeypatch.setattr("apps.telegram_bot.handlers.get_health_snapshot", lambda: health)
    monkeypatch.setattr("apps.telegram_bot.handlers.get_doctor_snapshot", lambda: doctor)

    for command in ("/health", "/doctor"):
        handle_update(
            {"message": {"text": command, "chat": {"id": 100, "type": "private"}, "from": {"id": 200}}},
            client,
            config(),
        )

    output = "\n".join(message[1] for message in client.messages)
    assert "Database" in output
    assert "Pending migrations" in output
    assert "🟢 jobapply-web.service: <b>active</b>" in output
    assert "🟢 <b>Overall: HEALTHY</b>" in output
    assert "test-token" not in output


def test_doctor_marks_failed_systemd_units_and_reports_overall_state():
    health = HealthSnapshot(True, 512, ())
    doctor = DoctorSnapshot(
        health,
        "master",
        False,
        0,
        (),
        (("jobapply-web.service", "active"), ("jobapply-backup.service", "failed")),
    )

    text = doctor_text("PRODUCTION", doctor)

    assert "🟢 jobapply-web.service: <b>active</b>" in text
    assert "🔴 jobapply-backup.service: <b>last backup failed</b>" in text
    assert "<code>journalctl -u jobapply-backup.service -n 100 --no-pager</code>" in text
    assert "🔴 <b>Overall: ACTION REQUIRED</b>" in text


def test_doctor_treats_inactive_scheduled_backup_as_healthy():
    successful_backup = HeartbeatStatus(
        "backup_worker",
        timezone.now(),
        False,
        "",
        datetime(2026, 8, 7, 8, 48, tzinfo=UTC),
    )
    health = HealthSnapshot(True, 512, (successful_backup,))
    doctor = DoctorSnapshot(
        health,
        "master",
        False,
        0,
        (),
        (("jobapply-web.service", "active"), ("jobapply-backup.service", "inactive")),
    )

    text = doctor_text("PRODUCTION", doctor)

    assert "✅ jobapply-backup.service: <b>last backup successful · 07.08.2026 10:48</b>" in text
    assert "journalctl -u jobapply-backup.service" not in text
    assert "🟢 <b>Overall: HEALTHY</b>" in text
