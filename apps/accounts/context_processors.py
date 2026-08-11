from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse

from .models import UserProfile


def account_mode(request: HttpRequest) -> dict[str, bool | str]:
    context: dict[str, bool | str] = {
        "is_demo_user": False,
        "ai_audit_url": "",
        "turnstile_enabled": bool(getattr(settings, "TURNSTILE_ENABLED", False)),
        "turnstile_site_key": str(getattr(settings, "TURNSTILE_SITE_KEY", "")),
    }
    if not request.user.is_authenticated:
        return context

    context["is_demo_user"] = UserProfile.objects.filter(
        user=request.user,
        is_demo_user=True,
    ).exists()
    if request.user.is_staff and settings.AI_AUDIT_URL:
        context["ai_audit_url"] = reverse(
            "ai_audit:swagger",
            kwargs={"audit_key": settings.AI_AUDIT_URL},
        )
    return context
