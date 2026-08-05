from pathlib import Path


def test_deploy_script_rejects_untracked_files_even_when_git_hides_them():
    script = (Path(__file__).parents[1] / "deploy" / "vps" / "jobapply-deploy.sh").read_text(encoding="utf-8")

    assert "status --porcelain --untracked-files=all" in script


def test_deploy_marker_is_shared_with_the_private_tmp_telegram_service():
    root = Path(__file__).parents[1]
    deployments = (root / "apps" / "telegram_bot" / "deployments.py").read_text(encoding="utf-8")
    telegram_unit = (root / "deploy" / "vps" / "systemd" / "jobapply-telegram-bot.service").read_text(encoding="utf-8")
    deploy_unit = (root / "deploy" / "vps" / "systemd" / "jobapply-deploy.service").read_text(encoding="utf-8")

    assert "/run/jobapply/deploy.requested" in deployments
    assert "PrivateTmp=true" in telegram_unit
    assert "RuntimeDirectory=jobapply" in telegram_unit
    assert "JOBAPPLY_DEPLOY_REQUEST_MARKER=/run/jobapply/deploy.requested" in telegram_unit
    assert "JOBAPPLY_DEPLOY_REQUEST_MARKER=/run/jobapply/deploy.requested" in deploy_unit
