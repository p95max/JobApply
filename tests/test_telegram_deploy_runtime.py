from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.telegram_bot import deployments
from apps.telegram_bot.deployments import apply_deploy_callback
from apps.telegram_bot.models import TelegramDeployRequest, TelegramDeployRequestStatus


def test_claim_deploy_request_creates_missing_parent_directory(monkeypatch, tmp_path):
    marker = tmp_path / "jobapply" / "deploy.requested"
    monkeypatch.setattr(deployments, "DEPLOY_REQUEST_MARKER", marker)

    assert not marker.parent.exists()
    assert deployments._claim_deploy_request(operation="deploy", target_commit="a" * 40) is True
    assert marker.exists()
    assert marker.parent.is_dir()

    deployments._release_deploy_request()


def test_claim_deploy_request_returns_none_on_runtime_filesystem_error(monkeypatch, tmp_path):
    marker = tmp_path / "jobapply" / "deploy.requested"
    monkeypatch.setattr(deployments, "DEPLOY_REQUEST_MARKER", marker)

    def fail_mkdir(*args, **kwargs):
        raise PermissionError("runtime directory is not writable")

    monkeypatch.setattr(type(marker.parent), "mkdir", fail_mkdir)

    assert deployments._claim_deploy_request(operation="deploy", target_commit="a" * 40) is None


@pytest.mark.django_db
def test_deploy_marker_failure_does_not_raise_or_start_service(monkeypatch):
    request = TelegramDeployRequest.objects.create(
        telegram_user_id=200,
        chat_id=100,
        current_commit="abc1234",
        target_commit="def5678",
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    started = []
    monkeypatch.setattr(deployments, "_claim_deploy_request", lambda **kwargs: None)
    monkeypatch.setattr(deployments, "_start_deploy_service", lambda: started.append(True) or True)

    result = apply_deploy_callback(
        request_id=request.pk,
        action="confirm",
        telegram_user_id=200,
        chat_id=100,
    )

    request.refresh_from_db()
    assert result.outcome == "failed"
    assert "runtime marker" in result.message
    assert request.status == TelegramDeployRequestStatus.FAILED
    assert started == []


def test_production_telegram_unit_uses_shared_marker_outside_private_tmp():
    unit = (deployments.settings.BASE_DIR / "deploy/vps/systemd/jobapply-telegram-bot.service").read_text(
        encoding="utf-8"
    )

    assert "PrivateTmp=true" in unit
    assert "JOBAPPLY_DEPLOY_REQUEST_MARKER=/var/lib/jobapply/runtime/deploy.requested" in unit


def test_deploy_script_resynchronizes_telegram_and_deploy_systemd_units():
    script = (deployments.settings.BASE_DIR / "deploy/vps/jobapply-deploy.sh").read_text(encoding="utf-8")

    assert "Synchronizing Telegram/deploy systemd units" in script
    assert 'deploy/vps/systemd/jobapply-telegram-bot.service"' in script
    assert 'deploy/vps/systemd/jobapply-deploy.service"' in script
    assert '"$SYSTEMD_DIR/"' in script
    assert "systemctl daemon-reload" in script
    assert "jobapply-rollback.sh" in script
    assert "/usr/local/sbin/jobapply-rollback" in script
    assert 'install -d -o root -g jobapply -m 0770 "$STATE_DIR/runtime"' in script
