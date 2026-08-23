from __future__ import annotations

import re
from pathlib import Path


def test_deploy_notifications_use_status_leds():
    script = Path("deploy/vps/jobapply-deploy-notify.sh").read_text(encoding="utf-8")

    assert re.search(r'result="UPDATED"\s+icon="🟢"', script)
    assert re.search(r'result="UP TO DATE"\s+icon="🟡"', script)
    assert "🔴 <b>JobApply %s failed" in script
