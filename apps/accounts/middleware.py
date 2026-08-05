from __future__ import annotations

from allauth.socialaccount.models import SocialAccount
from django.db.utils import ProgrammingError
from django.shortcuts import redirect
from django.urls import reverse


class ConsentRequiredMiddleware:
    """Require consent for authenticated users who signed in through Google OAuth."""

    EXEMPT_PATH_PREFIXES = (
        "/admin/",
        "/accounts/",
        "/static/",
        "/media/",
        "/impressum/",
        "/datenschutz/",
        "/nutzungsbedingungen/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        if any(path.startswith(prefix) for prefix in self.EXEMPT_PATH_PREFIXES):
            return self.get_response(request)

        if not request.user.is_authenticated:
            return self.get_response(request)

        consent_url = reverse("accounts:consent")
        if path == consent_url:
            return self.get_response(request)

        try:
            uses_google_oauth = SocialAccount.objects.filter(
                user=request.user,
                provider="google",
            ).exists()
        except ProgrammingError:
            return self.get_response(request)

        if not uses_google_oauth:
            return self.get_response(request)

        from apps.accounts.views import ensure_profile

        try:
            profile = ensure_profile(request.user)
        except ProgrammingError:
            return self.get_response(request)

        if not profile.google_data_access_consent:
            return redirect(consent_url)

        return self.get_response(request)
