from django.urls import path, include, reverse
from django.shortcuts import redirect, render
from django.contrib import admin

from apps.accounts.dashboard import dashboard
from apps.accounts.views_turnstile import google_login_gate
from allauth.socialaccount.providers.google.views import oauth2_login
from django.conf.urls.static import static


from config import settings

admin_path = f"{settings.ADMIN_URL.strip('/')}/" if getattr(settings, "ADMIN_URL", "") else None


def root(request):
    if request.user.is_authenticated:
        return redirect("/dashboard/")
    return render(request, "landing.html")


def google_only_login(request):
    next_url = request.GET.get("next", "/dashboard/")
    return redirect(f"{reverse('google_login_gate')}?next={next_url}")


urlpatterns = [
    path("", root, name="landing"),
    path("dashboard/", dashboard, name="dashboard"),

    path("accounts/login/", google_only_login),
    path("accounts/google/login/", google_login_gate, name="google_login_gate"),

    path("accounts/google/oauth/", oauth2_login, name="google_oauth_login"),
    path("i18n/", include("django.conf.urls.i18n")),

    path("accounts/", include("allauth.urls")),

    path("app/", include("apps.accounts.urls")),
    path("applications/", include("apps.applications.urls")),
    path("interviews/", include("apps.interviews.urls")),
    path("reports/", include("apps.reports.urls")),
    path("gmail_stats/", include("apps.gmail_stats.urls")),
    path("gmail_stats/", include("apps.gmail_assistant.urls")),
    path("", include("apps.legal.urls")),
    path("", include("apps.gmail_assistant.audit_urls")),
]

if admin_path:
    urlpatterns.append(path(admin_path, admin.site.urls))

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
