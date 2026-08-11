from __future__ import annotations

from django.contrib.auth import get_user_model
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.gmail_assistant.audit_views import (
    _pending_application_payload,
    _parse_positive_int,
    _require_audit_access,
)
from apps.gmail_assistant.services.bulk_create import (
    BULK_CREATE_MIN_CONFIDENCE,
    eligible_bulk_create_proposals,
)


@_require_audit_access
@require_GET
@never_cache
def high_confidence_applications(request: HttpRequest, *, audit_key: str):
    """List the exact pending create proposals eligible for explicit bulk creation."""
    try:
        limit = _parse_positive_int(request, "limit", default=50, maximum=500)
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
