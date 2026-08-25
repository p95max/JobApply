from __future__ import annotations

from typing import Any

from django.conf import settings


def is_configured_owner(*, user: Any) -> bool:
    """Return whether a user matches the configured owner email."""
    owner_email = settings.TELEGRAM_OWNER_EMAIL.strip().casefold()
    user_email = str(getattr(user, "email", "") or "").strip().casefold()
    return bool(owner_email and user_email == owner_email)
