from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import JobApplicationForm
from .models import JobApplication


@login_required
def list_applications(request):
    qs = JobApplication.objects.filter(user=request.user)

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()

    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(company__icontains=q) | Q(location__icontains=q))
    if status:
        qs = qs.filter(status=status)

    qs = qs[:200] 

    return render(request, "applications/list.html", {"items": qs, "q": q, "status": status})


@login_required
def create_application(request):
    if request.method == "POST":
        form = JobApplicationForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            obj.save()
            return redirect("applications:list")
    else:
        form = JobApplicationForm()

    return render(request, "applications/form.html", {"form": form, "mode": "create"})


@login_required
def update_application(request, pk: int):
    obj = get_object_or_404(JobApplication, pk=pk, user=request.user)

    if request.method == "POST":
        form = JobApplicationForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            return redirect("applications:list")
    else:
        form = JobApplicationForm(instance=obj)

    return render(request, "applications/form.html", {"form": form, "mode": "edit", "obj": obj})


@login_required
def delete_application(request, pk: int):
    obj = get_object_or_404(JobApplication, pk=pk, user=request.user)

    if request.method == "POST":
        obj.delete()
        return redirect("applications:list")

    return render(request, "applications/delete.html", {"obj": obj})
