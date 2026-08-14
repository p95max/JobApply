from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .forms import JobApplicationForm
from .models import ApplicationStatus, JobApplication
from .services.limits import ApplicationLimitError, ensure_application_capacity
from apps.gmail_assistant.models import AnalysisClassifier, ApplicationUpdateProposal, ProposalStatus
from apps.gmail_stats.models import GmailMessage

logger = logging.getLogger(__name__)


@login_required
def list_applications(request):
    PER_PAGE_DEFAULT = 15
    PER_PAGE_MIN = 10
    PER_PAGE_MAX = 50

    try:
        ai_processed_proposals = ApplicationUpdateProposal.objects.filter(
            user=request.user,
            application_id=OuterRef("pk"),
            status=ProposalStatus.ACCEPTED,
            analysis__classifier__in=(AnalysisClassifier.AI, AnalysisClassifier.RULE_AI),
        )
        qs = JobApplication.objects.filter(user=request.user).annotate(
            has_ai_processed_proposal=Exists(ai_processed_proposals)
        )

        q = (request.GET.get("q") or "").strip()
        status = (request.GET.get("status") or "").strip()
        ai_filter = (request.GET.get("ai") or "").strip()
        month = (request.GET.get("month") or "").strip()
        follow_up = request.GET.get("follow_up") == "1"
        sort = (request.GET.get("sort") or "-applied_at").strip()
        print_mode = (request.GET.get("print") == "1")
        all_apps_total = qs.count()

        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(company__icontains=q)
                | Q(location__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)

        if ai_filter == "processed":
            qs = qs.filter(has_ai_processed_proposal=True)
        elif ai_filter == "without":
            qs = qs.filter(has_ai_processed_proposal=False)
        else:
            ai_filter = ""

        if follow_up:
            qs = qs.filter(
                status=ApplicationStatus.APPLIED,
                recruiter_reply_at__isnull=True,
                applied_at__lt=timezone.now() - timedelta(days=14),
            )

        if month:
            try:
                year, mon = map(int, month.split("-"))
                start = timezone.make_aware(datetime(year, mon, 1, 0, 0, 0))
                end = timezone.make_aware(
                    datetime(
                        year + (1 if mon == 12 else 0),
                        (1 if mon == 12 else mon + 1),
                        1,
                        0,
                        0,
                        0,
                    )
                )
                qs = qs.filter(applied_at__gte=start, applied_at__lt=end)
            except ValueError:
                pass

        allowed_sorts = {
            "id", "-id",
            "applied_at", "-applied_at",
            "updated_at", "-updated_at",
            "title", "-title",
            "company", "-company",
            "source", "-source",
            "location", "-location",
            "status", "-status",
        }
        if sort not in allowed_sorts:
            sort = "-applied_at"

        qs = qs.order_by(sort)

        if print_mode:
            items = qs.order_by(sort)
            page_obj = None
            paginator = None
            per_page = None
        else:
            try:
                per_page = int(request.GET.get("per_page") or PER_PAGE_DEFAULT)
            except ValueError:
                per_page = PER_PAGE_DEFAULT
            per_page = max(PER_PAGE_MIN, min(PER_PAGE_MAX, per_page))
            paginator = Paginator(qs, per_page)
            page_obj = paginator.get_page(request.GET.get("page"))
            items = page_obj.object_list

        params = request.GET.copy()
        params.pop("page", None)
        base_qs = params.urlencode()

        return render(
            request,
            "applications/list.html",
            {
                "items": items,
                "page_obj": page_obj,
                "paginator": paginator,
                "q": q,
                "status": status,
                "ai_filter": ai_filter,
                "month": month,
                "follow_up": follow_up,
                "sort": sort,
                "per_page": per_page,
                "base_qs": base_qs,
                "print_mode": print_mode,
                "all_apps_total": all_apps_total,

            },
        )
    except Exception:
        logger.exception("list_applications failed user=%s", request.user.id)
        messages.error(request, "Could not load applications. Try again later.")
        return render(
            request,
            "applications/list.html",
            {
                "items": [],
                "page_obj": None,
                "paginator": None,
                "q": "",
                "status": "",
                "ai_filter": "",
                "month": "",
                "follow_up": False,
                "sort": "-applied_at",
                "per_page": PER_PAGE_DEFAULT,
                "base_qs": "",
                "print_mode": False,
                "all_apps_total": 0,
            },
        )



@login_required
def create_application(request):
    form = JobApplicationForm(request.POST or None)
    if request.method != "POST":
        return render(request, "applications/form.html", {"form": form, "mode": "create"})

    try:
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            with transaction.atomic():
                ensure_application_capacity(user=request.user)
                obj.save()
            messages.success(request, "Application created.")
            return redirect("applications:list")
    except ApplicationLimitError as error:
        form.add_error(None, str(error))
    except Exception:
        logger.exception("create_application failed user=%s", request.user.id)
        messages.error(request, "Could not create application. Try again later.")

    return render(request, "applications/form.html", {"form": form, "mode": "create"})


@login_required
def update_application(request, pk: int):
    obj = get_object_or_404(JobApplication, pk=pk, user=request.user)

    try:
        if request.method == "POST":
            form = JobApplicationForm(request.POST, instance=obj)
            if form.is_valid():
                form.save()
                messages.success(request, "Application updated.")
                return redirect("applications:list")
        else:
            form = JobApplicationForm(instance=obj)

        return render(request, "applications/form.html", {"form": form, "mode": "edit", "obj": obj})
    except Exception:
        logger.exception("update_application failed user=%s pk=%s", request.user.id, pk)
        messages.error(request, "Could not update application. Try again later.")
        form = JobApplicationForm(instance=obj)
        return render(request, "applications/form.html", {"form": form, "mode": "edit", "obj": obj})


@login_required
def delete_application(request, pk: int):
    obj = get_object_or_404(JobApplication, pk=pk, user=request.user)

    try:
        if request.method == "POST":
            obj.delete()
            messages.success(request, "Application deleted.")
            return redirect("applications:list")

        return render(request, "applications/delete.html", {"obj": obj})
    except Exception:
        logger.exception("delete_application failed user=%s pk=%s", request.user.id, pk)
        messages.error(request, "Could not delete application. Try again later.")
        return redirect("applications:list")


@require_POST
@login_required
@csrf_protect
def bulk_delete(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        ids = payload.get("ids", [])
        if not isinstance(ids, list) or len(ids) > settings.APPLICATION_BULK_DELETE_MAX_IDS:
            return HttpResponseBadRequest("Too many selected applications")
        ids = [int(x) for x in ids]
    except Exception:
        return HttpResponseBadRequest("Invalid payload")

    JobApplication.objects.filter(user=request.user, id__in=ids).delete()
    return JsonResponse({"deleted": len(ids)})


@require_POST
@login_required
def update_status(request, pk: int):
    status = (request.POST.get("status") or "").strip()

    allowed = {c[0] for c in JobApplication._meta.get_field("status").choices}
    if status not in allowed:
        return JsonResponse({"error": "Invalid status"}, status=400)

    try:
        app = JobApplication.objects.get(pk=pk, user=request.user)
    except JobApplication.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)
    except Exception:
        logger.exception("update_status failed user=%s pk=%s status=%s", request.user.id, pk, status)
        return JsonResponse({"error": "Unexpected error"}, status=500)

    try:
        app.status = status
        app.save(update_fields=["status"])
        return JsonResponse({"ok": True, "status": status})
    except Exception:
        logger.exception("update_status save failed user=%s pk=%s status=%s", request.user.id, pk, status)
        return JsonResponse({"error": "Unexpected error"}, status=500)


@login_required
def application_detail(request, pk: int):
    try:
        app = get_object_or_404(JobApplication, pk=pk, user=request.user)
        ai_processed = ApplicationUpdateProposal.objects.filter(
            user=request.user,
            application=app,
            status=ProposalStatus.ACCEPTED,
            analysis__classifier__in=(AnalysisClassifier.AI, AnalysisClassifier.RULE_AI),
        ).exists()
        gmail_messages = (
            GmailMessage.objects.filter(user=request.user)
            .filter(Q(application=app) | Q(proposals__application=app))
            .select_related("analysis")
            .prefetch_related("proposals")
            .distinct()
            .order_by("-received_at")
        )
        rejection_message = gmail_messages.filter(analysis__event_type="rejection").first()
        return render(
            request,
            "applications/detail.html",
            {
                "app": app,
                "ai_processed": ai_processed,
                "gmail_messages": gmail_messages,
                "rejection_at": rejection_message.received_at if rejection_message else None,
            },
        )
    except Http404:
        raise
    except Exception:
        logger.exception("application_detail failed user=%s pk=%s", request.user.id, pk)
        messages.error(request, "Could not load application. Try again later.")
        return redirect("applications:list")
