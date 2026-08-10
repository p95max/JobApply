from __future__ import annotations

from pathlib import Path


def test_deploy_notifications_use_status_leds():
    script = Path("deploy/vps/jobapply-deploy-notify.sh").read_text(encoding="utf-8")

    assert 'result="UPDATED"\n    icon="🟢"' in script
    assert 'result="UP TO DATE"\n    icon="🟡"' in script
    assert "🔴 <b>JobApply deploy failed" in script
