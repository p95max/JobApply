from __future__ import annotations

from django.conf import settings
from django.shortcuts import render


def _legal_context() -> dict[str, object]:
    context = {
        "provider_name": settings.LEGAL_PROVIDER_NAME,
        "provider_address": settings.LEGAL_PROVIDER_ADDRESS,
        "contact_email": settings.LEGAL_CONTACT_EMAIL,
        "privacy_contact_email": settings.LEGAL_PRIVACY_CONTACT_EMAIL,
        "supervisory_authority": settings.LEGAL_SUPERVISORY_AUTHORITY,
        "log_retention": settings.LEGAL_LOG_RETENTION,
        "demo_account_ttl_hours": settings.DEMO_ACCOUNT_TTL_HOURS,
    }
    return context


def impressum(request):
    return render(request, "legal/impressum.html", _legal_context())


def privacy(request):
    return render(request, "legal/privacy.html", _legal_context())


def terms(request):
    return render(request, "legal/terms.html", _legal_context())
