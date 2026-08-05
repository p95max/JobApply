from __future__ import annotations

from typing import Any

from django.conf import settings


def has_dev_tools_access(*, user: Any) -> bool:
    """Allow destructive/reanalysis development tools only to the configured owner."""
    owner_email = settings.TELEGRAM_OWNER_EMAIL.strip().casefold()
    user_email = str(getattr(user, "email", "") or "").strip().casefold()
    return bool(settings.GMAIL_ASSISTANT_DEV_TOOLS and owner_email and user_email == owner_email)
