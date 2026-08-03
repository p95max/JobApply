from __future__ import annotations

from os import getenv

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.http import HttpResponseForbidden


def _allowed_account_emails() -> set[str]:
    return {
        email.strip().lower()
        for email in getenv("ALLOWED_ACCOUNT_EMAILS", "").split(",")
        if email.strip()
    }


def _social_email(sociallogin) -> str:
    return (
        sociallogin.account.extra_data.get("email")
        or getattr(sociallogin.user, "email", "")
        or ""
    ).strip().lower()


class NoSignupAccountAdapter(DefaultAccountAdapter):
    """Block local email/password signup. Authentication is Google-only."""

    def is_open_for_signup(self, request):
        if getattr(request, "path", "") == "/accounts/signup/":
            return False
        return True


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Allow Google authentication only for explicitly allow-listed emails."""

    def _is_allowed(self, sociallogin) -> bool:
        allowed_emails = _allowed_account_emails()
        return bool(allowed_emails and _social_email(sociallogin) in allowed_emails)

    def is_open_for_signup(self, request, sociallogin):
        return self._is_allowed(sociallogin)

    def pre_social_login(self, request, sociallogin):
        if not self._is_allowed(sociallogin):
            raise ImmediateHttpResponse(
                HttpResponseForbidden("This Google account is not allowed to access JobApply.")
            )
        return super().pre_social_login(request, sociallogin)

    def get_connect_redirect_url(self, request, socialaccount):
        url = request.session.pop("drive_connect_next", None)
        if url:
            return url
        return super().get_connect_redirect_url(request, socialaccount)
