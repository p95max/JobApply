from __future__ import annotations

from django.conf import settings


def jobapply_url(path: str = "/") -> str:
    """Return an absolute JobApply URL for a local application path."""
    domain = str(getattr(settings, "DJANGO_SITE_DOMAIN", "jobapply.p95max.dev")).strip().strip("/")
    base_url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
    return f"{base_url}/{path.lstrip('/')}"
