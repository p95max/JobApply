from django.urls import path
from apps.gmail_stats.views import gmail_stats

urlpatterns = [
    path("stats/gmail/", gmail_stats, name="gmail_stats"),
]
