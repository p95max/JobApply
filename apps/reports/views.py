from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render

from apps.applications.models import JobApplication
from .services import build_stats, export_csv, export_xlsx, import_csv


@login_required
def statistics(request):
    qs = JobApplication.objects.filter(user=request.user)
    stats = build_stats(qs)
    return render(request, "reports/statistics.html", {"stats": stats})


@login_required
def export_report(request, fmt: str):
    qs = JobApplication.objects.filter(user=request.user)

    if fmt == "csv":
        content = export_csv(qs)
        resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="jobapply_export.csv"'
        return resp

    if fmt == "xlsx":
        content = export_xlsx(qs)
        resp = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = 'attachment; filename="jobapply_export.xlsx"'
        return resp

    return redirect("reports:statistics")


@login_required
def import_view(request):
    if request.method == "POST":
        f = request.FILES.get("file")
        if not f:
            return render(request, "reports/import.html", {"error": "No file uploaded."})

        result = import_csv(request.user, f.read())
        return render(request, "reports/import.html", {"result": result})

    return render(request, "reports/import.html")
