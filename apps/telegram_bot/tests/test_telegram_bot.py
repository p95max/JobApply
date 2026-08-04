from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.telegram_bot.config import TelegramConfig, parse_id_set
from apps.telegram_bot.handlers import _queue_deploy
from apps.telegram_bot.permissions import is_update_allowed
from apps.telegram_bot.texts import help_text


def make_config(**overrides):
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
    }
    values.update(overrides)
    return TelegramConfig(**values)


def test_parse_id_set_ignores_empty_values():
    assert parse_id_set("1, 2, ,3") == frozenset({1, 2, 3})


def test_parse_id_set_rejects_invalid_value():
    with pytest.raises(ValueError, match="Invalid Telegram ID"):
        parse_id_set("1,broken")


def test_private_allowed_update_is_accepted():
    update = {"message": {"chat": {"id": 100, "type": "private"}, "from": {"id": 200}}}
    assert is_update_allowed(update, make_config()) is True


def test_group_chat_is_rejected():
    update = {"message": {"chat": {"id": 100, "type": "group"}, "from": {"id": 200}}}
    assert is_update_allowed(update, make_config()) is False


@pytest.mark.django_db
def test_unknown_user_is_rejected():
    update = {"message": {"chat": {"id": 100, "type": "private"}, "from": {"id": 999}}}
    assert is_update_allowed(update, make_config()) is False


def test_help_text_escapes_environment():
    assert "&lt;prod&gt;" in help_text("<prod>")


def test_deploy_is_rejected_for_non_owner():
    update = {"message": {"chat": {"id": 100}, "from": {"id": 201}}}
    assert "only to the bot owner" in _queue_deploy(update, make_config())


@patch("apps.telegram_bot.handlers.subprocess.run")
def test_owner_can_queue_deploy(run_mock):
    run_mock.side_effect = [
        SimpleNamespace(returncode=3),
        SimpleNamespace(returncode=0, stderr=""),
    ]
    update = {"message": {"chat": {"id": 100}, "from": {"id": 200}}}

    reply = _queue_deploy(update, make_config())

    assert "Deploy queued" in reply
    assert run_mock.call_count == 2
    assert run_mock.call_args_list[1].args[0] == [
        "sudo",
        "-n",
        "systemctl",
        "--no-block",
        "start",
        "jobapply-deploy.service",
    ]
