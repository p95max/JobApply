from __future__ import annotations

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Ensures predictable redirects after 'process=connect'.
    """

    def get_connect_redirect_url(self, request, socialaccount):
        url = request.session.pop("drive_connect_next", None)
        if url:
            return url
        return super().get_connect_redirect_url(request, socialaccount)
