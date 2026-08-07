from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from apps.security.turnstile import verify_turnstile


def _safe_next_url(request, value: str | None) -> str:
    """Keep OAuth return URLs on this JobApply site."""
    candidate = (value or "").strip()
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return "/dashboard/"


def _oauth_redirect(next_url: str):
    return redirect(f"{reverse('google_oauth_login')}?{urlencode({'next': next_url})}")


def google_login_gate(request):
    next_url = _safe_next_url(request, request.POST.get("next") or request.GET.get("next"))

    # Without Turnstile, proceed directly to Google instead of showing a
    # redundant in-app confirmation page.
    if not settings.TURNSTILE_ENABLED:
        return _oauth_redirect(next_url)

    if request.method == "POST":
        token = request.POST.get("cf-turnstile-response", "")
        remote_ip = request.META.get("REMOTE_ADDR")
        result = verify_turnstile(token, remote_ip=remote_ip)

        if result.success:
            request.session["turnstile_passed"] = True
            request.session.modified = True
            return _oauth_redirect(next_url)

    return render(request, "accounts/google_login_gate.html", {
        "is_gate": True,
        "next": next_url,
        "turnstile_site_key": settings.TURNSTILE_SITE_KEY,
        "turnstile_enabled": settings.TURNSTILE_ENABLED,
    })

