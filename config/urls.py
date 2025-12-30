from django.contrib import admin
from django.urls import include, path
from django.http import HttpResponseRedirect
from allauth.socialaccount.providers.google.views import oauth2_login

from apps.accounts.views_turnstile import google_login_gate


def google_only_login(request):
    next_url = request.GET.get("next", "/")
    return HttpResponseRedirect(f"/accounts/google/login/?next={next_url}")


urlpatterns = [
    path("admin/", admin.site.urls),

    path("", google_login_gate),

    path("accounts/login/", google_only_login),
    path("accounts/google/login/", google_login_gate, name="google_login_gate"),
    path("accounts/google/oauth/", oauth2_login, name="google_oauth_login"),
    path("accounts/", include("allauth.urls")),

    path("app/", include("apps.accounts.urls")),
    path("applications/", include("apps.applications.urls")),
    path("interviews/", include("apps.interviews.urls")),
    path("reports/", include("apps.reports.urls")),
]
