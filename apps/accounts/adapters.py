from __future__ import annotations

from allauth.account.adapter import DefaultAccountAdapter


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

