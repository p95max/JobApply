from django.urls import path

from apps.gmail_assistant import usage_views, views

app_name = "gmail_assistant"

urlpatterns = [
    path("gmail/assistant/", views.gmail_assistant, name="gmail_assistant"),
    path("gmail/assistant/token-usage/", usage_views.token_usage, name="token_usage"),
    path("gmail/assistant/proposals/", views.gmail_assistant, name="gmail_proposals"),
    path("gmail/assistant/proposals/<int:pk>/", views.gmail_proposal_detail, name="gmail_proposal_detail"),
    path("gmail/assistant/proposals/<int:pk>/accept/", views.accept_gmail_proposal, name="accept_gmail_proposal"),
    path("gmail/assistant/proposals/<int:pk>/edit-accept/", views.edit_and_accept_gmail_proposal, name="edit_accept_gmail_proposal"),
    path("gmail/assistant/proposals/<int:pk>/assign/", views.assign_gmail_proposal, name="assign_gmail_proposal"),
    path("gmail/assistant/proposals/<int:pk>/reject/", views.reject_gmail_proposal, name="reject_gmail_proposal"),
    path("gmail/assistant/proposals/<int:pk>/ignore/", views.ignore_gmail_proposal, name="ignore_gmail_proposal"),
    path("gmail/assistant/settings/", views.gmail_assistant_settings, name="gmail_assistant_settings"),
    path("gmail/assistant/reset/", views.reset_gmail_assistant, name="reset_gmail_assistant"),
]
