from django.urls import path

from apps.gmail_assistant import audit_high_confidence, audit_views

app_name = "ai_audit"

urlpatterns = [
    path("<slug:audit_key>/", audit_views.swagger, name="swagger"),
    path("<slug:audit_key>/openapi.json", audit_high_confidence.openapi_schema, name="openapi_schema"),
    path("<slug:audit_key>/api/applications/", audit_views.applications, name="applications"),
    path(
        "<slug:audit_key>/api/pending-applications/",
        audit_views.pending_applications,
        name="pending_applications",
    ),
    path(
        "<slug:audit_key>/api/high-confidence-applications/",
        audit_high_confidence.high_confidence_applications,
        name="high_confidence_applications",
    ),
    path("<slug:audit_key>/api/ai-proposals/", audit_views.ai_proposals, name="ai_proposals"),
    path("<slug:audit_key>/api/gmail-analyses/", audit_views.gmail_analyses, name="gmail_analyses"),
    path(
        "<slug:audit_key>/api/applications/<int:application_id>/ai-history/",
        audit_views.application_ai_history,
        name="application_ai_history",
    ),
]
