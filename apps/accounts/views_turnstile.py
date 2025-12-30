from django.shortcuts import redirect, render
from django.urls import reverse
from django.conf import settings

from apps.security.turnstile import verify_turnstile


def google_login_gate(request):
    next_url = request.POST.get("next") or request.GET.get("next") or "/"

    if request.method == "POST":
        token = request.POST.get("cf-turnstile-response", "")
        remote_ip = request.META.get("REMOTE_ADDR")
        result = verify_turnstile(token, remote_ip=remote_ip)

        if result.success:
            return redirect(f"{reverse('google_oauth_login')}?next={next_url}")

    return render(
        request,
        "accounts/google_login_gate.html",
        {
            "next": next_url,
            "turnstile_site_key": settings.TURNSTILE_SITE_KEY,
            "turnstile_enabled": settings.TURNSTILE_ENABLED,
        },
    )
