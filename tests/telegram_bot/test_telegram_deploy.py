from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.telegram_bot import deployments
from apps.telegram_bot.config import TelegramConfig
from apps.telegram_bot.deployments import (
    DeployMenu,
    DeployPreparation,
    apply_deploy_callback,
    prepare_deploy_request,
)
from apps.telegram_bot.handlers import handle_update
from apps.telegram_bot.models import (
    TelegramDeployOperation,
    TelegramDeployRequest,
    TelegramDeployRequestStatus,
)


class FakeClient:
    def __init__(self):
        self.messages = []
        self.answers = []
        self.edits = []

    def send_message(self, chat_id, text, *, reply_markup=None):
        self.messages.append((chat_id, text, reply_markup))

    def answer_callback_query(self, callback_id, text):
        self.answers.append((callback_id, text))

    def edit_message_text(self, chat_id, message_id, text, *, reply_markup=None):
        self.edits.append((chat_id, message_id, text, reply_markup))


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
        "production_branch": "master",
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


def deploy_menu_callback(operation: str) -> dict:
    return {
        "callback_query": {
            "id": "menu-callback",
            "data": f"deploymenu:{operation}",
            "from": {"id": 200},
            "message": {"message_id": 77, "chat": {"id": 100, "type": "private"}},
        }
    }


@pytest.mark.django_db
def test_deploy_is_disabled_by_default():
    client = FakeClient()

    handle_update(deploy_command(), client, config(deploy_enabled=False))

    assert "Deploy disabled" in client.messages[0][1]


def test_deploy_marker_pins_operation_and_target(monkeypatch, tmp_path):
    marker = tmp_path / "jobapply-deploy.requested"
    monkeypatch.setattr(deployments, "DEPLOY_REQUEST_MARKER", marker)

    assert deployments._claim_deploy_request(operation="rollback", target_commit="a" * 40) is True
    assert marker.read_text() == f"rollback {'a' * 40}\n"

    deployments._release_deploy_request()
    assert not marker.exists()


@pytest.mark.django_db
def test_deploy_does_not_accept_branch_or_shell_arguments():
    client = FakeClient()
    update = deploy_command()
    update["message"]["text"] = "/deploy master && whoami"

    handle_update(update, client, config())

    assert "does not accept branch names" in client.messages[0][1]


@pytest.mark.django_db
def test_deploy_command_shows_latest_and_rollback_buttons(monkeypatch):
    monkeypatch.setattr(
        "apps.telegram_bot.handlers.get_deploy_menu",
        lambda branch: DeployMenu("abc1234", "d" * 40, "c" * 40),
    )
    client = FakeClient()

    handle_update(deploy_command(), client, config())

    _chat_id, text, markup = client.messages[0]
    assert "Current: <code>abc1234</code>" in text
    assert f"Latest master: <code>{'d' * 12}</code>" in text
    assert f"Rollback target: <code>{'c' * 12}</code>" in text
    assert markup["inline_keyboard"] == [
        [{"text": "🚀 Deploy latest", "callback_data": "deploymenu:deploy"}],
        [{"text": "↩️ Rollback last successful", "callback_data": "deploymenu:rollback"}],
    ]


@pytest.mark.django_db
def test_deploy_menu_selection_requires_second_confirmation(monkeypatch):
    request = TelegramDeployRequest.objects.create(
        telegram_user_id=200,
        chat_id=100,
        current_commit="abc1234",
        target_commit="d" * 40,
        operation=TelegramDeployOperation.DEPLOY,
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    monkeypatch.setattr(
        "apps.telegram_bot.handlers.prepare_deploy_request",
        lambda **kwargs: DeployPreparation(
            request,
            "Deploy confirmation required.\nCurrent: abc1234\nTarget: dddddddddddd",
            "pending",
        ),
    )
    client = FakeClient()

    handle_update(deploy_menu_callback("deploy"), client, config())

    assert client.edits[0][0:2] == (100, 77)
    assert "Deploy confirmation required" in client.edits[0][2]
    assert client.edits[0][3]["inline_keyboard"][0][0] == {
        "text": "🚀 Confirm deploy",
        "callback_data": f"deploy:{request.pk}:confirm",
    }


@pytest.mark.django_db
def test_rollback_menu_selection_uses_rollback_confirmation(monkeypatch):
    request = TelegramDeployRequest.objects.create(
        telegram_user_id=200,
        chat_id=100,
        current_commit="abc1234",
        target_commit="c" * 40,
        operation=TelegramDeployOperation.ROLLBACK,
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    monkeypatch.setattr(
        "apps.telegram_bot.handlers.prepare_deploy_request",
        lambda **kwargs: DeployPreparation(request, "Rollback confirmation required.", "pending"),
    )
    client = FakeClient()

    handle_update(deploy_menu_callback("rollback"), client, config())

    assert client.edits[0][3]["inline_keyboard"][0][0]["text"] == "✅ Confirm rollback"


@pytest.mark.django_db
def test_confirmed_deploy_is_one_time_and_owner_bound(monkeypatch):
    request = TelegramDeployRequest.objects.create(
        telegram_user_id=200,
        chat_id=100,
        current_commit="abc1234",
        target_commit="d" * 40,
        target_description="Deploy Gmail matching fixes",
        operation=TelegramDeployOperation.DEPLOY,
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    claimed = []
    monkeypatch.setattr(
        "apps.telegram_bot.deployments._claim_deploy_request",
        lambda **kwargs: claimed.append(kwargs) or True,
    )
    monkeypatch.setattr("apps.telegram_bot.deployments._start_deploy_service", lambda: True)

    result = apply_deploy_callback(
        request_id=request.pk,
        action="confirm",
        telegram_user_id=200,
        chat_id=100,
    )
    repeat = apply_deploy_callback(
        request_id=request.pk,
        action="confirm",
        telegram_user_id=200,
        chat_id=100,
    )
    foreign = apply_deploy_callback(
        request_id=request.pk,
        action="confirm",
        telegram_user_id=201,
        chat_id=100,
    )

    request.refresh_from_db()
    assert result.outcome == "queued"
    assert claimed == [{"operation": "deploy", "target_commit": "d" * 40}]
    assert "Deploy queued" in result.message
    assert request.status == TelegramDeployRequestStatus.QUEUED
    assert repeat.outcome == "already_processed"
    assert foreign.outcome == "not_found"


@pytest.mark.django_db
def test_confirmed_rollback_pins_tracked_target(monkeypatch):
    request = TelegramDeployRequest.objects.create(
        telegram_user_id=200,
        chat_id=100,
        current_commit="d" * 12,
        target_commit="c" * 40,
        target_description="Known good production commit",
        operation=TelegramDeployOperation.ROLLBACK,
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    claimed = []
    monkeypatch.setattr(
        "apps.telegram_bot.deployments._claim_deploy_request",
        lambda **kwargs: claimed.append(kwargs) or True,
    )
    monkeypatch.setattr("apps.telegram_bot.deployments._start_deploy_service", lambda: True)

    result = apply_deploy_callback(
        request_id=request.pk,
        action="confirm",
        telegram_user_id=200,
        chat_id=100,
    )

    assert result.outcome == "queued"
    assert "Rollback queued" in result.message
    assert claimed == [{"operation": "rollback", "target_commit": "c" * 40}]


def test_rollback_target_uses_last_success_after_failed_checkout(monkeypatch, tmp_path):
    last = tmp_path / "last"
    previous = tmp_path / "previous"
    last.write_text("b" * 40)
    previous.write_text("a" * 40)
    monkeypatch.setattr(deployments, "LAST_SUCCESSFUL_FILE", last)
    monkeypatch.setattr(deployments, "PREVIOUS_SUCCESSFUL_FILE", previous)
    monkeypatch.setattr(deployments, "_git_output", lambda *args: "c" * 40)

    assert deployments._rollback_target() == "b" * 40


def test_rollback_target_uses_previous_when_current_is_last_success(monkeypatch, tmp_path):
    last = tmp_path / "last"
    previous = tmp_path / "previous"
    last.write_text("b" * 40)
    previous.write_text("a" * 40)
    monkeypatch.setattr(deployments, "LAST_SUCCESSFUL_FILE", last)
    monkeypatch.setattr(deployments, "PREVIOUS_SUCCESSFUL_FILE", previous)
    monkeypatch.setattr(deployments, "_git_output", lambda *args: "b" * 40)

    assert deployments._rollback_target() == "a" * 40


@pytest.mark.django_db
def test_deploy_confirmation_shows_dates_for_current_and_target_commits(monkeypatch):
    def fake_git(*args):
        if args == ("rev-parse", "--short", "HEAD"):
            return "abc1234"
        if args[0] == "show" and "--format=%s" in args:
            return "Add deploy notification details"
        return ""

    monkeypatch.setattr("apps.telegram_bot.deployments.current_queue_status", lambda: None)
    monkeypatch.setattr("apps.telegram_bot.deployments._git_output", fake_git)
    monkeypatch.setattr("apps.telegram_bot.deployments._deploy_commits", lambda branch: ("abc1234", "d" * 40))
    monkeypatch.setattr(
        "apps.telegram_bot.deployments._commit_date",
        lambda revision: "06.08.2026 10:00" if revision == "HEAD" else "07.08.2026 11:00",
    )
    monkeypatch.setattr(
        "apps.telegram_bot.deployments._target_commit_description",
        lambda **_kwargs: "Add deploy notification details",
    )

    prepared = prepare_deploy_request(telegram_user_id=200, chat_id=100, branch="master", ttl_seconds=300)

    assert "Description: Add deploy notification details" in prepared.message
    assert "Current: abc1234 · 06.08.2026 10:00" in prepared.message
    assert f"Target: {'d' * 12} · 07.08.2026 11:00" in prepared.message


def test_commit_date_uses_a_readable_local_format(monkeypatch):
    calls = []
    monkeypatch.setattr(
        deployments,
        "_git_output",
        lambda *args: calls.append(args) or "07.08.2026 10:50",
    )

    assert deployments._commit_date("HEAD") == "07.08.2026 10:50"
    assert calls == [
        ("show", "-s", "--format=%cd", "--date=format-local:%d.%m.%Y %H:%M", "HEAD"),
    ]


@pytest.mark.django_db
def test_expired_deploy_confirmation_does_not_start_service(monkeypatch):
    called = []
    monkeypatch.setattr("apps.telegram_bot.deployments._start_deploy_service", lambda: called.append(True))
    request = TelegramDeployRequest.objects.create(
        telegram_user_id=200,
        chat_id=100,
        current_commit="abc1234",
        target_commit="d" * 40,
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
