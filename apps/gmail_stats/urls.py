from django.urls import path
from apps.gmail_stats import views

app_name = "gmail_stats"

urlpatterns = [
    path("gmail/", views.gmail_dashboard, name="gmail_dashboard"),
    path("gmail/assistant/", views.gmail_assistant, name="gmail_assistant"),
    path("gmail/assistant/proposals/", views.gmail_assistant, name="gmail_proposals"),
    path("gmail/assistant/proposals/<int:pk>/", views.gmail_proposal_detail, name="gmail_proposal_detail"),
    path("gmail/assistant/proposals/<int:pk>/accept/", views.accept_gmail_proposal, name="accept_gmail_proposal"),
    path(
        "gmail/assistant/proposals/<int:pk>/edit-accept/",
        views.edit_and_accept_gmail_proposal,
        name="edit_accept_gmail_proposal",
    ),
    path("gmail/assistant/proposals/<int:pk>/assign/", views.assign_gmail_proposal, name="assign_gmail_proposal"),
    path("gmail/assistant/proposals/<int:pk>/reject/", views.reject_gmail_proposal, name="reject_gmail_proposal"),
    path("gmail/assistant/proposals/<int:pk>/ignore/", views.ignore_gmail_proposal, name="ignore_gmail_proposal"),
    path("gmail/assistant/settings/", views.gmail_assistant_settings, name="gmail_assistant_settings"),

    path("gmail/api/stats/", views.gmail_stats_api, name="gmail_stats_api"),
    path("gmail/api/sync/", views.gmail_sync_api, name="gmail_sync_api"),
]

