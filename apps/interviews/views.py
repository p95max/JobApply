from __future__ import annotations

from django.shortcuts import redirect, render

from .forms import InterviewEventForm
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from .models import InterviewEvent, InterviewStatus


@login_required
def interview_list(request):
    items = InterviewEvent.objects.filter(user=request.user).select_related("application")[:200]
    return render(request, "interviews/list.html", {"items": items})


@login_required
@require_POST
def interview_status(request, pk: int):
    obj = get_object_or_404(InterviewEvent, pk=pk, user=request.user)
    status = (request.POST.get("status") or "").strip()

    allowed = {c.value for c in InterviewStatus}
    if status not in allowed:
        return HttpResponseBadRequest("Invalid status")

    obj.status = status
    obj.save(update_fields=["status"])
    return HttpResponse("ok")


@login_required
def interview_create(request):
    if request.method == "POST":
        form = InterviewEventForm(request.POST, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            obj.full_clean()
            obj.save()
            return redirect("interviews:list")
    else:
        form = InterviewEventForm(user=request.user)

    return render(request, "interviews/form.html", {"form": form})

@login_required
def interview_update(request, pk: int):
    obj = get_object_or_404(InterviewEvent, pk=pk, user=request.user)

    if request.method == "POST":
        form = InterviewEventForm(request.POST, instance=obj, user=request.user)
        if form.is_valid():
            form.save()
            return redirect("interviews:list")
    else:
        form = InterviewEventForm(instance=obj, user=request.user)

    return render(
        request,
        "interviews/form.html",
        {"form": form, "mode": "edit", "obj": obj},
    )

@login_required
def interview_delete(request, pk: int):
    obj = get_object_or_404(InterviewEvent, pk=pk, user=request.user)

    if request.method == "POST":
        obj.delete()
        return redirect("interviews:list")

    return render(request, "interviews/delete.html", {"obj": obj})
