from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.root, name="root"),
    path("consent/", views.consent, name="consent"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/delete-account/", views.delete_account, name="delete_account"),
]
