from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import InterviewEventForm
from .models import InterviewEvent


@login_required
def interview_list(request):
    items = InterviewEvent.objects.filter(user=request.user).select_related("application")[:200]
    return render(request, "interviews/list.html", {"items": items})


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
def interview_delete(request, pk: int):
    obj = get_object_or_404(InterviewEvent, pk=pk, user=request.user)

    if request.method == "POST":
        obj.delete()
        return redirect("interviews:list")

    return render(request, "interviews/delete.html", {"obj": obj})
