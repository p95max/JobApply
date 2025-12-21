from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("consent/", views.consent, name="consent"),
]
