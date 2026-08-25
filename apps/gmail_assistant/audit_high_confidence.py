from __future__ import annotations

import json
from django.contrib.auth import get_user_model
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.gmail_assistant import audit_views
from apps.gmail_assistant.audit_views import (
    _audit_pagination,
    _audit_query_parameters,
    _pending_application_payload,
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
            "parameters": _audit_query_parameters(),
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
        pagination = _audit_pagination(request)
    except ValueError as error:
        return JsonResponse({"detail": str(error)}, status=400)

    user = None
    if pagination.user_id:
        user = get_user_model().objects.filter(pk=pagination.user_id).first()
        if user is None:
            return JsonResponse(
                {
                    "count": 0,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                    "min_confidence": BULK_CREATE_MIN_CONFIDENCE,
                    "results": [],
                }
            )

    proposals = eligible_bulk_create_proposals(user=user)
    total = len(proposals)
    results = [
        _pending_application_payload(proposal)
        for proposal in proposals[pagination.offset : pagination.offset + pagination.limit]
    ]
    return JsonResponse(
        {
            "count": total,
            "limit": pagination.limit,
            "offset": pagination.offset,
            "min_confidence": BULK_CREATE_MIN_CONFIDENCE,
            "results": results,
        }
    )
