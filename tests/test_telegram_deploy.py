from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.telegram_bot.config import TelegramConfig
from apps.telegram_bot.deployments import DeployPreparation, apply_deploy_callback, prepare_deploy_request
from apps.telegram_bot.handlers import handle_update
from apps.telegram_bot.models import TelegramDeployRequest, TelegramDeployRequestStatus


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
        "deploy_enabled": True,
        "deploy_confirmation_ttl_seconds": 300,
        "production_branch": "agent/vps-no-docker-deploy",
    }
    values.update(overrides)
    return TelegramConfig(**values)


def deploy_command() -> dict:
    return {
        "message": {
            "text": "/deploy",
            "chat": {"id": 100, "type": "private"},
            "from": {"id": 200},
        }
    }


@pytest.mark.django_db
def test_deploy_is_disabled_by_default():
    client = FakeClient()

    handle_update(deploy_command(), client, config(deploy_enabled=False))

    assert client.messages[0][1] == "Deploy is disabled by configuration."


@pytest.mark.django_db
def test_deploy_does_not_accept_branch_or_shell_arguments():
    client = FakeClient()
    update = deploy_command()
    update["message"]["text"] = "/deploy master && whoami"

    handle_update(update, client, config())

    assert "does not accept branch names" in client.messages[0][1]


@pytest.mark.django_db
def test_deploy_requires_confirmation_with_current_and_target_commit(monkeypatch):
    client = FakeClient()
    request = TelegramDeployRequest.objects.create(
        telegram_user_id=200,
        chat_id=100,
        current_commit="abc1234",
        target_commit="def5678",
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    monkeypatch.setattr(
        "apps.telegram_bot.handlers.prepare_deploy_request",
        lambda **kwargs: DeployPreparation(
            request,
            "Deploy confirmation required.\nCurrent: abc1234\nTarget: def5678",
            "pending",
        ),
    )

    handle_update(deploy_command(), client, config())

    _chat_id, text, markup = client.messages[0]
    assert "Current: abc1234" in text
    assert "Target: def5678" in text
    assert markup["inline_keyboard"][0][0]["callback_data"] == f"deploy:{request.pk}:confirm"


@pytest.mark.django_db
def test_confirmed_deploy_is_one_time_and_owner_bound(monkeypatch):
    monkeypatch.setattr("apps.telegram_bot.deployments.current_queue_status", lambda: None)
    monkeypatch.setattr("apps.telegram_bot.deployments._deploy_commits", lambda branch: ("abc1234", "def5678"))
    monkeypatch.setattr("apps.telegram_bot.deployments._claim_deploy_request", lambda: True)
    monkeypatch.setattr("apps.telegram_bot.deployments._start_deploy_service", lambda: True)
    prepared = prepare_deploy_request(
        telegram_user_id=200,
        chat_id=100,
        branch="agent/vps-no-docker-deploy",
        ttl_seconds=300,
    )
    assert prepared.request is not None

    result = apply_deploy_callback(
        request_id=prepared.request.pk,
        action="confirm",
        telegram_user_id=200,
        chat_id=100,
    )
    repeat = apply_deploy_callback(
        request_id=prepared.request.pk,
        action="confirm",
        telegram_user_id=200,
        chat_id=100,
    )
    foreign = apply_deploy_callback(
        request_id=prepared.request.pk,
        action="confirm",
        telegram_user_id=201,
        chat_id=100,
    )

    prepared.request.refresh_from_db()
    assert result.outcome == "queued"
    assert prepared.request.status == TelegramDeployRequestStatus.QUEUED
    assert repeat.outcome == "already_processed"
    assert foreign.outcome == "not_found"


@pytest.mark.django_db
def test_expired_deploy_confirmation_does_not_start_service(monkeypatch):
    called = []
    monkeypatch.setattr("apps.telegram_bot.deployments._start_deploy_service", lambda: called.append(True))
    request = TelegramDeployRequest.objects.create(
        telegram_user_id=200,
        chat_id=100,
        current_commit="abc1234",
        target_commit="def5678",
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    result = apply_deploy_callback(
        request_id=request.pk,
        action="confirm",
        telegram_user_id=200,
        chat_id=100,
    )

    request.refresh_from_db()
    assert result.outcome == "expired"
    assert request.status == TelegramDeployRequestStatus.EXPIRED
    assert called == []
