from django.contrib import admin
from django.urls import include, path
from allauth.socialaccount.providers.google.views import oauth2_login

urlpatterns = [
    path("admin/", admin.site.urls),

    path("", oauth2_login),
    path("accounts/", include("allauth.urls")),

    path("app/", include("apps.accounts.urls")),
    path("applications/", include("apps.applications.urls")),
    path("interviews/", include("apps.interviews.urls")),
    path("reports/", include("apps.reports.urls")),
]

