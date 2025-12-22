from __future__ import annotations
from django.shortcuts import get_object_or_404, redirect
from .forms import JobApplicationForm
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from datetime import datetime
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from .models import JobApplication


@login_required
def list_applications(request):
    qs = JobApplication.objects.filter(user=request.user)

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    month = (request.GET.get("month") or "").strip()
    sort = (request.GET.get("sort") or "-applied_at").strip()

    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(company__icontains=q)
            | Q(location__icontains=q)
        )

    if status:
        qs = qs.filter(status=status)

    if month:
        try:
            year, mon = map(int, month.split("-"))
            start = timezone.make_aware(datetime(year, mon, 1, 0, 0, 0))
            if mon == 12:
                end = timezone.make_aware(datetime(year + 1, 1, 1, 0, 0, 0))
            else:
                end = timezone.make_aware(datetime(year, mon + 1, 1, 0, 0, 0))
            qs = qs.filter(applied_at__gte=start, applied_at__lt=end)
        except ValueError:
            pass

    allowed_sorts = {"applied_at", "-applied_at", "updated_at", "-updated_at"}
    if sort not in allowed_sorts:
        sort = "-applied_at"

    qs = qs.order_by(sort)[:200]

    return render(
        request,
        "applications/list.html",
        {
            "items": qs,
            "q": q,
            "status": status,
            "month": month,
            "sort": sort,
        },
    )


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



@require_POST
@login_required
def update_status(request, pk):
    status = request.POST.get("status")

    if status not in {
        "applied", "screen", "interview", "offer", "rejected"
    }:
        return JsonResponse({"error": "Invalid status"}, status=400)

    app = JobApplication.objects.get(pk=pk, user=request.user)
    app.status = status
    app.save(update_fields=["status"])

    return JsonResponse({"ok": True, "status": status})

@login_required
def application_detail(request, pk):
    app = get_object_or_404(
        JobApplication,
        pk=pk,
        user=request.user,
    )

    return render(
        request,
        "applications/detail.html",
        {"app": app},
    )
