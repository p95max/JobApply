from __future__ import annotations

from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.applications.models import JobApplication
from apps.gmail_stats.services.credentials import get_google_credentials_for_user
from apps.gmail_stats.services.gmail_client import GmailClient
from apps.gmail_stats.services.apply_proposal import ProposalApplyError, apply_proposal, review_proposal
from apps.gmail_stats.services.sync import sync_gmail_messages_for_user
from apps.gmail_stats.models import (
    ApplicationUpdateProposal,
    GmailAssistantSettings,
    GmailMessage,
    GmailSyncState,
    ProposalStatus,
)


@login_required
def gmail_dashboard(request):
    return render(request, "gmail_stats/dashboard.html")


@login_required
def gmail_assistant(request):
    proposal_queryset = (
        ApplicationUpdateProposal.objects.filter(user=request.user)
        .select_related("message", "analysis", "application")
        .order_by("-message__received_at", "-created_at")
    )
    proposals = proposal_queryset
    status = request.GET.get("status", ProposalStatus.PENDING)
    if status in ProposalStatus.values:
        proposals = proposals.filter(status=status)
    settings, _ = GmailAssistantSettings.objects.get_or_create(user=request.user)
    return render(
        request,
        "gmail_stats/assistant.html",
        {
            "proposals": proposals[:50],
            "selected_status": status,
            "proposal_statuses": ProposalStatus,
            "settings": settings,
            "pending_count": proposal_queryset.filter(status=ProposalStatus.PENDING).count(),
        },
    )


@login_required
def gmail_proposal_detail(request, pk: int):
    proposal = get_object_or_404(
        ApplicationUpdateProposal.objects.select_related("message", "analysis", "application"),
        pk=pk,
        user=request.user,
    )
    candidates = JobApplication.objects.filter(user=request.user).exclude(status__in=["archived", "rejected"])
    return render(
        request,
        "gmail_stats/proposal_detail.html",
        {"proposal": proposal, "candidates": candidates},
    )


@login_required
@require_POST
def accept_gmail_proposal(request, pk: int):
    proposal = get_object_or_404(ApplicationUpdateProposal, pk=pk, user=request.user)
    try:
        result = apply_proposal(proposal=proposal, user=request.user)
    except ProposalApplyError as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request,
            "Proposal was already accepted." if result.already_accepted else "Proposal accepted.",
        )
    return redirect("gmail_stats:gmail_assistant")


@login_required
@require_POST
def edit_and_accept_gmail_proposal(request, pk: int):
    proposal = get_object_or_404(ApplicationUpdateProposal, pk=pk, user=request.user)
    overrides = {
        "application": {
            field: request.POST[field]
            for field in ("title", "company", "location")
            if request.POST.get(field)
        },
        "interview": {
            field: request.POST[field]
            for field in ("starts_at", "location", "notes")
            if request.POST.get(field)
        },
    }
    try:
        apply_proposal(proposal=proposal, user=request.user, overrides=overrides)
    except ProposalApplyError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Proposal accepted with your edits.")
    return redirect("gmail_stats:gmail_assistant")


@login_required
@require_POST
def assign_gmail_proposal(request, pk: int):
    proposal = get_object_or_404(ApplicationUpdateProposal, pk=pk, user=request.user)
    application = get_object_or_404(JobApplication, pk=request.POST.get("application_id"), user=request.user)
    proposal.application = application
    proposal.match_method = "manual"
    proposal.save(update_fields=["application", "match_method", "updated_at"])
    messages.success(request, "Application assigned for review.")
    return redirect("gmail_stats:gmail_proposal_detail", pk=pk)


@login_required
@require_POST
def reject_gmail_proposal(request, pk: int):
    proposal = get_object_or_404(ApplicationUpdateProposal, pk=pk, user=request.user)
    try:
        review_proposal(proposal=proposal, user=request.user, status=ProposalStatus.REJECTED)
    except ProposalApplyError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Proposal rejected.")
    return redirect("gmail_stats:gmail_assistant")


@login_required
@require_POST
def ignore_gmail_proposal(request, pk: int):
    proposal = get_object_or_404(ApplicationUpdateProposal, pk=pk, user=request.user)
    try:
        review_proposal(proposal=proposal, user=request.user, status=ProposalStatus.IGNORED)
    except ProposalApplyError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Proposal ignored.")
    return redirect("gmail_stats:gmail_assistant")


@login_required
@require_POST
def gmail_assistant_settings(request):
    settings, _ = GmailAssistantSettings.objects.get_or_create(user=request.user)
    enabled = request.POST.get("ai_enabled") == "1"
    was_enabled = settings.ai_enabled
    settings.ai_enabled = enabled
    if enabled and settings.ai_consent_at is None:
        settings.ai_consent_at = timezone.now()
    settings.save(update_fields=["ai_enabled", "ai_consent_at", "updated_at"])

    if enabled and not was_enabled:
        credentials = get_google_credentials_for_user(request.user)
        if not credentials:
            messages.warning(
                request,
                "AI analysis enabled, but Gmail is not connected. Reconnect Google and then sync Gmail.",
            )
        else:
            try:
                result = sync_gmail_messages_for_user(
                    user=request.user,
                    gmail_client=GmailClient(credentials),
                    days=180,
                    max_results_each=500,
                    reanalyze_existing=True,
                )
            except (RuntimeError, ValueError) as error:
                messages.warning(request, f"AI analysis enabled, but Gmail sync failed: {error}")
            else:
                messages.success(
                    request,
                    f"AI analysis enabled. Gmail synced; {result['proposals_created']} suggestion(s) created.",
                )
    else:
        messages.success(request, "AI analysis setting updated.")
    return redirect("gmail_stats:gmail_assistant")


@login_required
def gmail_stats_api(request):
    try:
        days = int(request.GET.get("days", "180"))
    except ValueError:
        return JsonResponse({"error": "days must be an integer"}, status=400)
    if not 1 <= days <= 365:
        return JsonResponse({"error": "days must be between 1 and 365"}, status=400)
    since = timezone.now() - timedelta(days=days)

    qs = GmailMessage.objects.filter(user=request.user, received_at__gte=since)

    qs = qs.exclude(direction="outbound")
    responses = qs.exclude(detected_type__in=["unknown", "noise"]).count()
    rejections = qs.filter(detected_type="rejection").count()
    invites = qs.filter(detected_type="invite").count()
    auto_ack = qs.filter(detected_type="auto_ack").count()

    state = GmailSyncState.objects.filter(user=request.user).first()
    last_synced_at = state.last_synced_at.isoformat() if state and state.last_synced_at else None

    return JsonResponse({
        "days": days,
        "responses": responses,
        "rejections": rejections,
        "invites": invites,
        "auto_ack": auto_ack,
        "last_synced_at": last_synced_at,
    })


@login_required
def gmail_sync_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    try:
        days = int(request.GET.get("days", "180"))
    except ValueError:
        return JsonResponse({"error": "days must be an integer"}, status=400)
    if not 1 <= days <= 365:
        return JsonResponse({"error": "days must be between 1 and 365"}, status=400)

    creds = get_google_credentials_for_user(request.user)
    if not creds:
        return JsonResponse(
            {"error": "Google Gmail not connected. Reconnect Google with gmail.readonly scope."},
            status=403,
        )

    gmail = GmailClient(creds)

    try:
        gmail.list_message_ids(query=f"newer_than:{min(days, 7)}d", max_results=1)
    except RuntimeError as e:
        msg = str(e)
        if "accessNotConfigured" in msg or "Gmail API has not been used" in msg:
            return JsonResponse(
                {"error": "Gmail API is disabled for your Google Cloud project. Enable Gmail API in Google Cloud Console and retry."},
                status=403,
            )
        if "insufficientPermissions" in msg:
            return JsonResponse(
                {"error": "Missing permission (gmail.readonly). Reconnect Google and grant Gmail access."},
                status=403,
            )
        return JsonResponse({"error": f"Gmail access failed: {msg}"}, status=403)
    except Exception as e:
        return JsonResponse({"error": f"Gmail access failed: {e}"}, status=403)

    res = sync_gmail_messages_for_user(
        user=request.user,
        gmail_client=gmail,
        days=days,
        max_results_each=500,
    )
    return JsonResponse({"ok": True, "result": res})

