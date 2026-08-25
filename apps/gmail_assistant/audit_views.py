from __future__ import annotations

from dataclasses import dataclass
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
    GmailAnalysis,
    ProposalStatus,
)
from apps.gmail_stats.models import GmailProcessingStatus


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


@dataclass(frozen=True)
class AuditPagination:
    limit: int
    offset: int
    user_id: int = 0


def _audit_pagination(request: HttpRequest, *, include_user_id: bool = True) -> AuditPagination:
    return AuditPagination(
        limit=_parse_positive_int(
            request,
            "limit",
            default=50,
            maximum=settings.AI_AUDIT_API_MAX_PAGE_SIZE,
        ),
        offset=_parse_positive_int(request, "offset", default=0, maximum=1_000_000),
        user_id=(
            _parse_positive_int(request, "user_id", default=0, maximum=2_147_483_647)
            if include_user_id
            else 0
        ),
    )


def _pagination_openapi_parameters() -> list[dict[str, object]]:
    return [
        {
            "name": "limit",
            "in": "query",
            "schema": {"type": "integer", "maximum": settings.AI_AUDIT_API_MAX_PAGE_SIZE},
        },
        {"name": "offset", "in": "query", "schema": {"type": "integer", "minimum": 0}},
    ]


def _audit_query_parameters(*, include_user_id: bool = True, include_status: bool = False):
    parameters = []
    if include_status:
        parameters.append({"name": "status", "in": "query", "schema": {"type": "string"}})
    if include_user_id:
        parameters.append({"name": "user_id", "in": "query", "schema": {"type": "integer"}})
    return [*parameters, *_pagination_openapi_parameters()]


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


def _application_payload(application: JobApplication) -> dict[str, object]:
    return {
        "id": application.pk,
        "owner_id": application.user_id,
        "company": application.company,
        "title": application.title,
        "location": application.location or None,
        "source": application.source or None,
        "status": application.status,
        "applied_at": _iso(application.applied_at),
        "recruiter_reply_at": _iso(application.recruiter_reply_at),
        "created_at": _iso(application.created_at),
        "updated_at": _iso(application.updated_at),
    }


def _pending_application_payload(proposal: ApplicationUpdateProposal) -> dict[str, object]:
    """Return all pending suggestions, including those not yet linked to an app."""
    application_change = proposal.changes.get("application") if isinstance(proposal.changes, dict) else None
    proposed_application = (
        {
            field: application_change.get(field)
            for field in ("title", "company", "location", "source", "status", "applied_at")
            if field in application_change
        }
        if isinstance(application_change, dict)
        else None
    )
    application = proposal.application
    temporary_create_id = proposal.changes.get("pending_create_proposal_id") if isinstance(proposal.changes, dict) else None
    return {
        "proposal_id": proposal.pk,
        "owner_id": proposal.user_id,
        "proposal_type": proposal.proposal_type,
        "created_at": _iso(proposal.created_at),
        "application": _application_payload(application) if application else None,
        "proposed_application": proposed_application,
        "matching": {
            "score": proposal.match_score,
            "method": proposal.match_method or None,
            "temporary_create_proposal_id": temporary_create_id if isinstance(temporary_create_id, int) else None,
        },
        "analysis": {
            "id": proposal.analysis_id,
            "event_type": proposal.analysis.event_type,
            "classifier": proposal.analysis.classifier,
            "confidence": proposal.analysis.confidence,
            "analyzed_at": _iso(proposal.analysis.analyzed_at),
        },
    }


def _analysis_reason(*, analysis: GmailAnalysis, proposals: list[ApplicationUpdateProposal]) -> str:
    """Return a redacted, operational explanation for the audit endpoint."""
    if proposals:
        return "proposal_created"
    if analysis.message.processing_status == GmailProcessingStatus.FAILED:
        return f"processing_failed:{analysis.message.processing_error or 'unknown'}"
    if analysis.message.processing_status == GmailProcessingStatus.IGNORED:
        return "ignored_by_pipeline"
    if not analysis.is_job_related:
        return "not_job_related"
    if analysis.event_type in {"noise", "unknown"}:
        return f"non_actionable_event:{analysis.event_type}"
    return "no_actionable_change_detected"


def _analysis_payload(analysis: GmailAnalysis) -> dict[str, object]:
    proposals = list(analysis.proposals.all())
    extracted = analysis.extracted_data if isinstance(analysis.extracted_data, dict) else {}
    matching = [
        {
            "proposal_id": proposal.pk,
            "application_id": proposal.application_id,
            "method": proposal.match_method or None,
            "score": proposal.match_score,
        }
        for proposal in proposals
    ]
    return {
        "analysis_id": analysis.pk,
        "owner_id": analysis.user_id,
        "gmail_message_id": analysis.message.message_id,
        "event_type": analysis.event_type,
        "classifier": analysis.classifier,
        "confidence": analysis.confidence,
        "analyzed_at": _iso(analysis.analyzed_at),
        "proposal_created": bool(proposals),
        "proposal_ids": [proposal.pk for proposal in proposals],
        "matching": matching,
        "extracted_application": {
            "company": extracted.get("company"),
            "position_title": extracted.get("position_title"),
            "location": extracted.get("location"),
        },
        "ignored": analysis.message.processing_status == GmailProcessingStatus.IGNORED,
        "reason": _analysis_reason(analysis=analysis, proposals=proposals),
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
            "applications_url": reverse("ai_audit:applications", kwargs={"audit_key": audit_key}),
            "pending_applications_url": reverse(
                "ai_audit:pending_applications",
                kwargs={"audit_key": audit_key},
            ),
            "proposals_url": reverse("ai_audit:ai_proposals", kwargs={"audit_key": audit_key}),
            "analyses_url": reverse("ai_audit:gmail_analyses", kwargs={"audit_key": audit_key}),
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
                    "parameters": _audit_query_parameters(include_status=True),
                    "responses": {"200": {"description": "Paginated, redacted audit records."}},
                }
            },
            "/api/applications/": {
                "get": {
                    "summary": "List all application records",
                    "description": "Includes applications with and without AI proposal history.",
                    "parameters": _audit_query_parameters(include_status=True),
                    "responses": {"200": {"description": "Paginated application metadata."}},
                }
            },
            "/api/pending-applications/": {
                "get": {
                    "summary": "List pending Gmail application suggestions",
                    "description": (
                        "Includes every pending proposal. Linked applications and extracted "
                        "proposed application values are included when available."
                    ),
                    "parameters": _audit_query_parameters(),
                    "responses": {"200": {"description": "Paginated pending application metadata."}},
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
                        *_pagination_openapi_parameters(),
                    ],
                    "responses": {"200": {"description": "Redacted AI proposal history."}},
                }
            },
            "/api/gmail-analyses/": {
                "get": {
                    "summary": "List redacted Gmail analysis decisions",
                    "description": (
                        "Includes proposal and matching outcomes, including analyses "
                        "that created no proposal."
                    ),
                    "parameters": _audit_query_parameters(),
                    "responses": {"200": {"description": "Paginated redacted decision records."}},
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
def applications(request: HttpRequest, *, audit_key: str):
    try:
        pagination = _audit_pagination(request)
    except ValueError as error:
        return JsonResponse({"detail": str(error)}, status=400)

    queryset = JobApplication.objects.all().order_by("-updated_at", "-pk")
    status = request.GET.get("status", "").strip()
    if status:
        valid_statuses = {choice for choice, _ in JobApplication._meta.get_field("status").choices}
        if status not in valid_statuses:
            return JsonResponse({"detail": "status is not valid."}, status=400)
        queryset = queryset.filter(status=status)
    if pagination.user_id:
        queryset = queryset.filter(user_id=pagination.user_id)

    total = queryset.count()
    results = [
        _application_payload(application)
        for application in queryset[pagination.offset : pagination.offset + pagination.limit]
    ]
    return JsonResponse(
        {"count": total, "limit": pagination.limit, "offset": pagination.offset, "results": results}
    )


@_require_audit_access
@require_GET
@never_cache
def pending_applications(request: HttpRequest, *, audit_key: str):
    """List every pending proposal, including unlinked application suggestions."""
    try:
        pagination = _audit_pagination(request)
    except ValueError as error:
        return JsonResponse({"detail": str(error)}, status=400)

    queryset = (
        ApplicationUpdateProposal.objects.filter(status=ProposalStatus.PENDING)
        .select_related("application", "analysis")
        .order_by("-message__received_at", "-pk")
    )
    if pagination.user_id:
        queryset = queryset.filter(user_id=pagination.user_id)
    total = queryset.count()
    results = [
        _pending_application_payload(proposal)
        for proposal in queryset[pagination.offset : pagination.offset + pagination.limit]
    ]
    return JsonResponse(
        {"count": total, "limit": pagination.limit, "offset": pagination.offset, "results": results}
    )


@_require_audit_access
@require_GET
@never_cache
def ai_proposals(request: HttpRequest, *, audit_key: str):
    try:
        pagination = _audit_pagination(request)
    except ValueError as error:
        return JsonResponse({"detail": str(error)}, status=400)

    queryset = _ai_proposals_queryset()
    status = request.GET.get("status", "").strip()
    if status:
        if status not in ProposalStatus.values:
            return JsonResponse({"detail": "status is not valid."}, status=400)
        queryset = queryset.filter(status=status)
    if pagination.user_id:
        queryset = queryset.filter(user_id=pagination.user_id)

    total = queryset.count()
    records = [
        _proposal_payload(proposal)
        for proposal in queryset[pagination.offset : pagination.offset + pagination.limit]
    ]
    return JsonResponse(
        {"count": total, "limit": pagination.limit, "offset": pagination.offset, "results": records}
    )


@_require_audit_access
@require_GET
@never_cache
def gmail_analyses(request: HttpRequest, *, audit_key: str):
    """Expose every persisted analysis decision without email content or tokens."""
    try:
        pagination = _audit_pagination(request)
    except ValueError as error:
        return JsonResponse({"detail": str(error)}, status=400)

    queryset = (
        GmailAnalysis.objects.select_related("message")
        .prefetch_related("proposals")
        .order_by("-analyzed_at", "-pk")
    )
    if pagination.user_id:
        queryset = queryset.filter(user_id=pagination.user_id)
    total = queryset.count()
    records = [
        _analysis_payload(analysis)
        for analysis in queryset[pagination.offset : pagination.offset + pagination.limit]
    ]
    return JsonResponse(
        {"count": total, "limit": pagination.limit, "offset": pagination.offset, "results": records}
    )


@_require_audit_access
@require_GET
@never_cache
def application_ai_history(request: HttpRequest, *, audit_key: str, application_id: int):
    try:
        pagination = _audit_pagination(request, include_user_id=False)
    except ValueError as error:
        return JsonResponse({"detail": str(error)}, status=400)

    application = get_object_or_404(JobApplication, pk=application_id)
    proposals = _ai_proposals_queryset().filter(application=application)
    results = [
        _proposal_payload(proposal)
        for proposal in proposals[pagination.offset : pagination.offset + pagination.limit]
    ]
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
            "limit": pagination.limit,
            "offset": pagination.offset,
            "results": results,
        }
    )
