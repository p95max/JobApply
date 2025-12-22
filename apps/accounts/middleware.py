from __future__ import annotations

from django.shortcuts import redirect
from django.urls import reverse
from django.db.utils import ProgrammingError


class ConsentRequiredMiddleware:
    """
    Enforces mandatory consent acceptance after OAuth login.
    If user is authenticated but has not accepted consent -> redirect to consent page.
    """

    EXEMPT_PATH_PREFIXES = (
        "/admin/",
        "/accounts/",
        "/static/",
        "/media/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        if any(path.startswith(p) for p in self.EXEMPT_PATH_PREFIXES):
            return self.get_response(request)

        if not request.user.is_authenticated:
            return self.get_response(request)

        consent_url = reverse("accounts:consent")

        if path == consent_url:
            return self.get_response(request)

        from apps.accounts.views import ensure_profile

        try:
            profile = ensure_profile(request.user)
        except ProgrammingError:
            return self.get_response(request)

        if not profile.google_data_access_consent:
            return redirect(consent_url)

        return self.get_response(request)
