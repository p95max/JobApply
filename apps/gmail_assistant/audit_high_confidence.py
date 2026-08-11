from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.gmail_assistant import audit_views
from apps.gmail_assistant.audit_views import (
    _pending_application_payload,
    _parse_positive_int,
    _require_audit_access,
)
from apps.gmail_assistant.services.bulk_create import (
    BULK_CREATE_MIN_CONFIDENCE,
    eligible_bulk_create_proposals,
)


def openapi_schema(request: HttpRequest, *, audit_key: str):
    """Extend the existing staff schema without changing its compatibility routes."""
    response = audit_views.openapi_schema(request, audit_key=audit_key)
    if response.status_code != 200:
        return response

    payload = json.loads(response.content)
    payload["info"]["title"] = "JobApply Gmail audit API"
    payload["info"]["description"] = (
        "Read-only staff audit API for Gmail application processing, proposal matching, "
        "and application records. Email bodies, subjects, credentials, and private review "
        "notes are never exposed."
    )
    payload["paths"]["/api/high-confidence-applications/"] = {
        "get": {
            "summary": "Create high-confidence applications candidates",
            "description": (
                "Lists the exact pending create proposals currently eligible for the explicit "
                "bulk-create action. This endpoint is read-only and does not create applications."
            ),
            "parameters": [
                {"name": "user_id", "in": "query", "schema": {"type": "integer"}},
                {
                    "name": "limit",
                    "in": "query",
                    "schema": {
                        "type": "integer",
                        "maximum": settings.AI_AUDIT_API_MAX_PAGE_SIZE,
                    },
                },
                {"name": "offset", "in": "query", "schema": {"type": "integer", "minimum": 0}},
            ],
            "responses": {
                "200": {
                    "description": "Paginated high-confidence create candidates and active threshold."
                }
            },
        }
    }
    response.content = json.dumps(payload)
    return response


@_require_audit_access
@require_GET
@never_cache
def high_confidence_applications(request: HttpRequest, *, audit_key: str):
    """List the exact pending create proposals eligible for explicit bulk creation."""
    try:
        limit = _parse_positive_int(
            request,
            "limit",
            default=50,
            maximum=settings.AI_AUDIT_API_MAX_PAGE_SIZE,
        )
        offset = _parse_positive_int(request, "offset", default=0, maximum=1_000_000)
        user_id = _parse_positive_int(request, "user_id", default=0, maximum=2_147_483_647)
    except ValueError as error:
        return JsonResponse({"detail": str(error)}, status=400)

    user = None
    if user_id:
        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None:
            return JsonResponse(
                {
                    "count": 0,
                    "limit": limit,
                    "offset": offset,
                    "min_confidence": BULK_CREATE_MIN_CONFIDENCE,
                    "results": [],
                }
            )

    proposals = eligible_bulk_create_proposals(user=user)
    total = len(proposals)
    results = [
        _pending_application_payload(proposal)
        for proposal in proposals[offset : offset + limit]
    ]
    return JsonResponse(
        {
            "count": total,
            "limit": limit,
            "offset": offset,
            "min_confidence": BULK_CREATE_MIN_CONFIDENCE,
            "results": results,
        }
    )
