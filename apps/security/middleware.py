from __future__ import annotations

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class TurnstileAnonymousGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "TURNSTILE_ENABLED", False):
            return self.get_response(request)

        if getattr(request, "user", None) is not None and request.user.is_authenticated:
            return self.get_response(request)

        if request.session.get("turnstile_passed"):
            return self.get_response(request)

        path = request.path
        gate_path = reverse("google_login_gate")

        if (
            path == gate_path
            or path.startswith("/accounts/google/")
            or path.startswith("/accounts/social/")
            or path.startswith("/static/")
            or path.startswith("/media/")
            or path.startswith("/admin/")
            or path in ("/favicon.ico", "/robots.txt")
        ):
            return self.get_response(request)

        return redirect(f"{gate_path}?next={path}")
