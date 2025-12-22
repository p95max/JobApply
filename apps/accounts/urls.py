from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.google_login_landing, name="landing"),
    path("consent/", views.consent, name="consent"),
]
