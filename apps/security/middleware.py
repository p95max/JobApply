from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.crypto import salted_hmac

admin_prefix = f"/{settings.ADMIN_URL.strip('/')}/" if getattr(settings, "ADMIN_URL", "") else None


def _admin_prefix() -> str | None:
    admin_url = str(getattr(settings, "ADMIN_URL", "")).strip("/")
    return f"/{admin_url}/" if admin_url else None


def _admin_client_ip(request) -> str:
    if getattr(settings, "ADMIN_TRUST_X_FORWARDED_FOR", False):
        forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR", "")).split(",")[0].strip()
        if forwarded:
            return forwarded
    return str(request.META.get("REMOTE_ADDR", "unknown"))


def _admin_login_key(request) -> str:
    identifier = salted_hmac("jobapply-admin-login", _admin_client_ip(request)).hexdigest()
    return f"admin-login-failures:{identifier}"


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
            or path.startswith("/static/")
            or path.startswith("/media/")
            or (admin_prefix and path.startswith(admin_prefix))
            or path in ("/favicon.ico", "/robots.txt")
        ):
            return self.get_response(request)

        return redirect(f"{gate_path}?next={path}")


class AdminAccessPolicyMiddleware:
    """Optionally restrict the entire Django Admin to configured network addresses."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        prefix = _admin_prefix()
        allowed_ips = getattr(settings, "ADMIN_ALLOWED_IPS", frozenset())
        if prefix and request.path.startswith(prefix) and allowed_ips:
            if _admin_client_ip(request) not in allowed_ips:
                return HttpResponseForbidden("Admin access is restricted.")
        return self.get_response(request)


class AdminLoginThrottleMiddleware:
    """Throttle password failures on Django Admin without affecting OAuth users."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        prefix = _admin_prefix()
        login_path = f"{prefix}login/" if prefix else ""
        is_login_post = request.method == "POST" and request.path == login_path
        key = _admin_login_key(request) if is_login_post else ""
        if is_login_post and (cache.get(key) or 0) >= settings.ADMIN_LOGIN_MAX_FAILURES:
            return HttpResponse(
                "Too many failed admin sign-in attempts. Please try again later.",
                status=429,
            )

        response = self.get_response(request)
        if not is_login_post:
            return response

        if response.status_code in {301, 302, 303, 307, 308}:
            cache.delete(key)
        elif response.status_code == 200:
            if cache.add(key, 1, timeout=settings.ADMIN_LOGIN_FAILURE_WINDOW_SECONDS):
                return response
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, timeout=settings.ADMIN_LOGIN_FAILURE_WINDOW_SECONDS)
        return response
