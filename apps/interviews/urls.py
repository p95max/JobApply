from django.urls import path

from . import views

app_name = "interviews"

urlpatterns = [
    path("", views.interview_list, name="list"),
    path("<int:pk>/status/", views.interview_status, name="status"),

    path("create/", views.interview_create, name="create"),
    path("<int:pk>/edit/", views.interview_update, name="edit"),
    path("<int:pk>/delete/", views.interview_delete, name="delete"),
]
