from pathlib import Path


def test_deploy_script_rejects_untracked_files_even_when_git_hides_them():
    script = (Path(__file__).parents[1] / "deploy" / "vps" / "jobapply-deploy.sh").read_text(encoding="utf-8")

    assert "status --porcelain --untracked-files=all" in script
