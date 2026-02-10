from django.urls import path
from apps.gmail_stats.views import gmail_stats, gmail_sync_view

urlpatterns = [
    path("stats/gmail/", gmail_stats, name="gmail_stats"),
    path("stats/gmail/sync/", gmail_sync_view, name="gmail_sync"),
]
