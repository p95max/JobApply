from __future__ import annotations

from allauth.account.adapter import DefaultAccountAdapter


class NoSignupAccountAdapter(DefaultAccountAdapter):
    """
    Google OAuth-only project: block local signups.
    """

    def is_open_for_signup(self, request):
        return False
