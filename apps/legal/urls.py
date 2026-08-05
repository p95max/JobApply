from django.urls import path

from . import views

app_name = "legal"

urlpatterns = [
    path("impressum/", views.impressum, name="impressum"),
    path("datenschutz/", views.privacy, name="privacy"),
    path("nutzungsbedingungen/", views.terms, name="terms"),
]
