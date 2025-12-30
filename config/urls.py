from django.urls import path, include, reverse
from django.shortcuts import redirect
from django.contrib import admin

from apps.accounts.views_turnstile import google_login_gate
from allauth.socialaccount.providers.google.views import oauth2_login

from config import settings

admin_path = f"{settings.ADMIN_URL.strip('/')}/" if getattr(settings, "ADMIN_URL", "") else None


def root(request):
    return redirect(f"{reverse('google_login_gate')}?next=/")

def google_only_login(request):
    next_url = request.GET.get("next", "/")
    return redirect(f"{reverse('google_login_gate')}?next={next_url}")

urlpatterns = [
    path("", root),

    path("accounts/login/", google_only_login),
    path("accounts/google/login/", google_login_gate, name="google_login_gate"),

    path("accounts/google/oauth/", oauth2_login, name="google_oauth_login"),

    path("accounts/", include("allauth.urls")),

    path("app/", include("apps.accounts.urls")),
    path("applications/", include("apps.applications.urls")),
    path("interviews/", include("apps.interviews.urls")),
    path("reports/", include("apps.reports.urls")),
]

if admin_path:
    urlpatterns.append(path(admin_path, admin.site.urls))