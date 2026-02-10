from django.urls import path
from apps.gmail_stats import views

urlpatterns = [
    path("gmail/", views.gmail_dashboard, name="gmail_dashboard"),

    path("gmail/api/stats/", views.gmail_stats_api, name="gmail_stats_api"),
    path("gmail/api/sync/", views.gmail_sync_api, name="gmail_sync_api"),
]

