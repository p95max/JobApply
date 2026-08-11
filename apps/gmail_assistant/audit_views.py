from __future__ import annotations

from functools import wraps

from django.conf import settings
from django.http import Http404, HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.applications.models import JobApplication
from apps.gmail_assistant.models import (
    AnalysisClassifier,
    ApplicationUpdateProposal,
    ProposalStatus,
)


def _require_audit_access(view):
    """Hide the audit routes unless their secret URL and staff session both match."""

    @wraps(view)
    def wrapped(request: HttpRequest, *args, audit_key: str, **kwargs):
        configured_key = settings.AI_AUDIT_URL
        if not configured_key or not constant_time_compare(audit_key, configured_key):
            raise Http404
        if not request.user.is_authenticated or not request.user.is_staff:
            raise Http404
        response = view(request, *args, audit_key=audit_key, **kwargs)
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response["Referrer-Policy"] = "same-origin"
        return response

    return wrapped


def _iso(value):
    return value.isoformat() if value else None


def _parse_positive_int(request: HttpRequest, name: str, *, default: int, maximum: int) -> int:
    raw_value = request.GET.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer.") from error
    if value < 0 or value > maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}.")
    return value


def _proposal_payload(proposal: ApplicationUpdateProposal) -> dict[str, object]:
    application = proposal.application
    return {
        "proposal_id": proposal.pk,
        "owner_id": proposal.user_id,
        "proposal_type": proposal.proposal_type,
        "proposal_status": proposal.status,
        "reviewed_at": _iso(proposal.reviewed_at),
        "created_at": _iso(proposal.created_at),
        "matching": {
            "score": proposal.match_score,
            "method": proposal.match_method or None,
        },
        "analysis": {
            "id": proposal.analysis_id,
            "classifier": proposal.analysis.classifier,
            "event_type": proposal.analysis.event_type,
            "confidence": proposal.analysis.confidence,
            "model_name": proposal.analysis.model_name or None,
            "prompt_version": proposal.analysis.prompt_version,
            "analyzed_at": _iso(proposal.analysis.analyzed_at),
        },
        "application": (
            {
                "id": application.pk,
                "company": application.company,
                "title": application.title,
                "status": application.status,
                "applied_at": _iso(application.applied_at),
            }
            if application
            else None
        ),
    }


def _ai_proposals_queryset():
    return (
        ApplicationUpdateProposal.objects.filter(
            analysis__classifier__in=(AnalysisClassifier.AI, AnalysisClassifier.RULE_AI)
        )
        .select_related("analysis", "application", "user")
        .order_by("-analysis__analyzed_at", "-pk")
    )


@_require_audit_access
@require_GET
@never_cache
def swagger(request: HttpRequest, *, audit_key: str):
    return render(
        request,
        "gmail_assistant/ai_audit_docs.html",
        {
            "audit_key": audit_key,
            "schema_url": reverse("ai_audit:openapi_schema", kwargs={"audit_key": audit_key}),
            "proposals_url": reverse("ai_audit:ai_proposals", kwargs={"audit_key": audit_key}),
        },
    )


@_require_audit_access
@require_GET
@never_cache
def openapi_schema(request: HttpRequest, *, audit_key: str):
    base_url = request.build_absolute_uri(
        reverse("ai_audit:swagger", kwargs={"audit_key": audit_key})
    ).rstrip("/")
    schema = {
        "openapi": "3.0.3",
        "info": {
            "title": "JobApply AI audit API",
            "version": "1.0.0",
            "description": (
                "Read-only staff audit API. It exposes AI processing metadata and linked "
                "application records, but never Gmail bodies, message subjects, credentials, "
                "or review notes."
            ),
        },
        "servers": [{"url": base_url}],
        "security": [{"sessionAuth": []}],
        "paths": {
            "/api/ai-proposals/": {
                "get": {
                    "summary": "List proposals processed by AI",
                    "parameters": [
                        {"name": "status", "in": "query", "schema": {"type": "string"}},
                        {"name": "user_id", "in": "query", "schema": {"type": "integer"}},
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {
                                "type": "integer",
                                "maximum": settings.AI_AUDIT_API_MAX_PAGE_SIZE,
                            },
                        },
                        {
                            "name": "offset",
                            "in": "query",
                            "schema": {"type": "integer", "minimum": 0},
                        },
                    ],
                    "responses": {"200": {"description": "Paginated, redacted audit records."}},
                }
            },
            "/api/applications/{application_id}/ai-history/": {
                "get": {
                    "summary": "List AI proposal history for one application",
                    "parameters": [
                        {
                            "name": "application_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {
                                "type": "integer",
                                "maximum": settings.AI_AUDIT_API_MAX_PAGE_SIZE,
                            },
                        },
                        {
                            "name": "offset",
                            "in": "query",
                            "schema": {"type": "integer", "minimum": 0},
                        },
                    ],
                    "responses": {"200": {"description": "Redacted AI proposal history."}},
                }
            },
        },
        "components": {
            "securitySchemes": {
                "sessionAuth": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": settings.SESSION_COOKIE_NAME,
                }
            }
        },
    }
    return JsonResponse(schema)


@_require_audit_access
@require_GET
@never_cache
def ai_proposals(request: HttpRequest, *, audit_key: str):
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

    queryset = _ai_proposals_queryset()
    status = request.GET.get("status", "").strip()
    if status:
        if status not in ProposalStatus.values:
            return JsonResponse({"detail": "status is not valid."}, status=400)
        queryset = queryset.filter(status=status)
    if user_id:
        queryset = queryset.filter(user_id=user_id)

    total = queryset.count()
    records = [_proposal_payload(proposal) for proposal in queryset[offset : offset + limit]]
    return JsonResponse({"count": total, "limit": limit, "offset": offset, "results": records})


@_require_audit_access
@require_GET
@never_cache
def application_ai_history(request: HttpRequest, *, audit_key: str, application_id: int):
    try:
        limit = _parse_positive_int(
            request,
            "limit",
            default=50,
            maximum=settings.AI_AUDIT_API_MAX_PAGE_SIZE,
        )
        offset = _parse_positive_int(request, "offset", default=0, maximum=1_000_000)
    except ValueError as error:
        return JsonResponse({"detail": str(error)}, status=400)

    application = get_object_or_404(JobApplication, pk=application_id)
    proposals = _ai_proposals_queryset().filter(application=application)
    results = [_proposal_payload(proposal) for proposal in proposals[offset : offset + limit]]
    return JsonResponse(
        {
            "application": {
                "id": application.pk,
                "owner_id": application.user_id,
                "company": application.company,
                "title": application.title,
                "status": application.status,
            },
            "count": proposals.count(),
            "limit": limit,
            "offset": offset,
            "results": results,
        }
    )
