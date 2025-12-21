from django.urls import path

from . import views

app_name = "applications"

urlpatterns = [
    path("", views.list_applications, name="list"),
    path("create/", views.create_application, name="create"),
    path("<int:pk>/edit/", views.update_application, name="edit"),
    path("<int:pk>/delete/", views.delete_application, name="delete"),
]
