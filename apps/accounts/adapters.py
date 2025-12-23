from __future__ import annotations

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class NoSignupAccountAdapter(DefaultAccountAdapter):
    """
    Google OAuth-only project:
    - block local (email/password) signup
    - allow social signup (Google) so new users can be created on first login
    """

    def is_open_for_signup(self, request):
        if getattr(request, "path", "").startswith("/accounts/google/"):
            return True

        if getattr(request, "path", "") == "/accounts/signup/":
            return False

        return True


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def get_connect_redirect_url(self, request, socialaccount):
        url = request.session.pop("drive_connect_next", None)
        if url:
            return url
        return super().get_connect_redirect_url(request, socialaccount)


