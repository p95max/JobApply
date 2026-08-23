from pathlib import Path


def test_deploy_script_rejects_untracked_files_even_when_git_hides_them():
    script = (Path(__file__).parents[1] / "deploy" / "vps" / "jobapply-deploy.sh").read_text(encoding="utf-8")

    assert "status --porcelain --untracked-files=all" in script


def test_deploy_marker_is_shared_between_telegram_and_deploy_services():
    root = Path(__file__).parents[1]
    deployments = (root / "apps" / "telegram_bot" / "deployments.py").read_text(encoding="utf-8")
    telegram_unit = (root / "deploy" / "vps" / "systemd" / "jobapply-telegram-bot.service").read_text(encoding="utf-8")
    deploy_unit = (root / "deploy" / "vps" / "systemd" / "jobapply-deploy.service").read_text(encoding="utf-8")
    install_ops = (root / "deploy" / "vps" / "install-ops.sh").read_text(encoding="utf-8")

    marker = "/var/lib/jobapply/runtime/deploy.requested"
    assert marker in deployments
    assert "PrivateTmp=true" in telegram_unit
    assert f"JOBAPPLY_DEPLOY_REQUEST_MARKER={marker}" in telegram_unit
    assert f"JOBAPPLY_DEPLOY_REQUEST_MARKER={marker}" in deploy_unit
    assert f"ExecStopPost=/usr/bin/rm -f {marker}" in deploy_unit
    assert "/var/lib/jobapply/runtime" in install_ops
    assert "-m 0770 /var/lib/jobapply/runtime" in install_ops


def test_rollback_runner_is_installed_and_does_not_reverse_migrations():
    root = Path(__file__).parents[1]
    deploy_script = (root / "deploy" / "vps" / "jobapply-deploy.sh").read_text(encoding="utf-8")
    rollback_script = (root / "deploy" / "vps" / "jobapply-rollback.sh").read_text(encoding="utf-8")

    assert "jobapply-rollback.sh" in deploy_script
    assert "/usr/local/sbin/jobapply-rollback" in deploy_script
    assert "reset --hard" in rollback_script
    assert "migrate --noinput" in rollback_script
    assert "migrate --fake" not in rollback_script
    assert "migrate --plan" not in rollback_script
    assert "reverse migrations" in rollback_script
