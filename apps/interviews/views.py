from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import InterviewEventForm
from .models import InterviewEvent, InterviewStatus

logger = logging.getLogger(__name__)


@login_required
def interview_list(request):
    try:
        items = (
            InterviewEvent.objects.filter(user=request.user)
            .select_related("application")[:200]
        )
        return render(request, "interviews/list.html", {"items": items})
    except Exception:
        logger.exception("interview_list failed user=%s", request.user.id)
        messages.error(request, "Could not load interviews. Try again later.")
        return render(request, "interviews/list.html", {"items": []})


@login_required
@require_POST
def interview_status(request, pk: int):
    status = (request.POST.get("status") or "").strip()
    allowed = {c.value for c in InterviewStatus}

    if status not in allowed:
        return HttpResponseBadRequest("Invalid status")

    try:
        obj = get_object_or_404(InterviewEvent, pk=pk, user=request.user)
        obj.status = status
        obj.save(update_fields=["status"])
        return HttpResponse("ok")
    except Exception:
        logger.exception("interview_status failed user=%s pk=%s status=%s", request.user.id, pk, status)
        return HttpResponse("error", status=500)


@login_required
def interview_create(request):
    try:
        if request.method == "POST":
            form = InterviewEventForm(request.POST, user=request.user)
            if form.is_valid():
                obj = form.save(commit=False)
                obj.user = request.user
                obj.full_clean()
                obj.save()
                messages.success(request, "Interview created.")
                return redirect("interviews:list")
        else:
            form = InterviewEventForm(user=request.user)

        return render(request, "interviews/form.html", {"form": form})
    except Exception:
        logger.exception("interview_create failed user=%s", request.user.id)
        messages.error(request, "Could not create interview. Try again later.")
        form = InterviewEventForm(user=request.user)
        return render(request, "interviews/form.html", {"form": form})


@login_required
def interview_update(request, pk: int):
    obj = get_object_or_404(InterviewEvent, pk=pk, user=request.user)

    try:
        if request.method == "POST":
            form = InterviewEventForm(request.POST, instance=obj, user=request.user)
            if form.is_valid():
                form.save()
                messages.success(request, "Interview updated.")
                return redirect("interviews:list")
        else:
            form = InterviewEventForm(instance=obj, user=request.user)

        return render(
            request,
            "interviews/form.html",
            {"form": form, "mode": "edit", "obj": obj},
        )
    except Exception:
        logger.exception("interview_update failed user=%s pk=%s", request.user.id, pk)
        messages.error(request, "Could not update interview. Try again later.")
        form = InterviewEventForm(instance=obj, user=request.user)
        return render(
            request,
            "interviews/form.html",
            {"form": form, "mode": "edit", "obj": obj},
        )


@login_required
def interview_delete(request, pk: int):
    obj = get_object_or_404(InterviewEvent, pk=pk, user=request.user)

    try:
        if request.method == "POST":
            obj.delete()
            messages.success(request, "Interview deleted.")
            return redirect("interviews:list")

        return render(request, "interviews/delete.html", {"obj": obj})
    except Exception:
        logger.exception("interview_delete failed user=%s pk=%s", request.user.id, pk)
        messages.error(request, "Could not delete interview. Try again later.")
        return redirect("interviews:list")
