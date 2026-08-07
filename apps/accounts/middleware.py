from __future__ import annotations

from allauth.socialaccount.models import SocialAccount
from django.contrib import messages
from django.db.utils import ProgrammingError
from django.shortcuts import redirect, render
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


class DemoUserRestrictionsMiddleware:
    """Render safe previews for demo users and block all connected-service actions."""

    OAUTH_PATH_PREFIXES = (
        "/accounts/google/",
        "/accounts/social/",
    )
    PREVIEW_PATH_PREFIXES = (
        "/gmail_stats/",
        "/reports/",
        "/app/settings/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        is_oauth_path = any(request.path.startswith(prefix) for prefix in self.OAUTH_PATH_PREFIXES)
        is_preview_path = any(request.path.startswith(prefix) for prefix in self.PREVIEW_PATH_PREFIXES)
        if not is_oauth_path and not is_preview_path:
            return self.get_response(request)

        try:
            from apps.accounts.models import UserProfile

            is_demo_user = UserProfile.objects.filter(
                user=request.user,
                is_demo_user=True,
            ).exists()
        except ProgrammingError:
            return self.get_response(request)

        if not is_demo_user:
            return self.get_response(request)

        if is_preview_path and request.method == "GET":
            return render(
                request,
                "guest/service_preview.html",
                {"preview_kind": self._preview_kind(request.path)},
            )

        messages.info(request, "Sign in with Google to use this connected service.")
        return redirect("dashboard")

    @staticmethod
    def _preview_kind(path: str) -> str:
        if "/gmail/assistant/" in path:
            return "assistant"
        if path.startswith("/gmail_stats/"):
            return "gmail"
        if path.startswith("/reports/"):
            return "reports"
        return "connections"
