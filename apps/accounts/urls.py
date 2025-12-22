from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.root, name="root"),
    path("consent/", views.consent, name="consent"),
]
