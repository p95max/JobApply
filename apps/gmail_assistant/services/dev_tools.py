from __future__ import annotations

from typing import Any

from django.conf import settings

from apps.security.ownership import is_configured_owner


def has_dev_tools_access(*, user: Any) -> bool:
    """Allow destructive/reanalysis development tools only to the configured owner."""
    return bool(settings.GMAIL_ASSISTANT_DEV_TOOLS and is_configured_owner(user=user))
