from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required

from apps.applications.models import JobApplication

from .drive import (
    disconnect_drive,
    download_file,
    get_drive_status,
    list_backups,
    upload_backup,
)
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


@login_required
def drive_backups(request):
    status = get_drive_status(request.user)

    backups = []
    error = None

    if not status.get("connected") or not status.get("has_refresh_token"):
        return render(
            request,
            "reports/drive_backups.html",
            {
                "drive_status": status,
                "backups": [],
                "error": None,
            },
        )

    try:
        backups = list_backups(request.user, limit=30)
    except Exception as e:
        error = str(e)

    return render(
        request,
        "reports/drive_backups.html",
        {
            "drive_status": status,
            "backups": backups,
            "error": error,
        },
    )


@login_required
def drive_export(request, fmt: str):
    qs = JobApplication.objects.filter(user=request.user).order_by("-applied_at")
    ts = timezone.now().strftime("%Y%m%d-%H%M%S")

    try:
        if fmt == "csv":
            content = export_csv(qs)
            filename = f"jobapply-{ts}.csv"
            upload_backup(
                request.user,
                filename,
                content,
                "text/csv",
                root_name="JobApply",
                subfolder="backups",
            )
            messages.success(request, "Backup uploaded to Google Drive (CSV).")
            return redirect("reports:drive_backups")

        if fmt == "xlsx":
            content = export_xlsx(qs)
            filename = f"jobapply-{ts}.xlsx"
            upload_backup(
                request.user,
                filename,
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                root_name="JobApply",
                subfolder="backups",   # или None
            )
            messages.success(request, "Backup uploaded to Google Drive (XLSX).")
            return redirect("reports:drive_backups")

        return redirect("reports:drive_backups")

    except Exception as e:
        messages.error(request, f"Drive export failed: {e}")
        return redirect("reports:drive_backups")


@login_required
def drive_restore(request, file_id: str):
    try:
        raw = download_file(request.user, file_id)
        result = import_csv(request.user, raw)
        messages.success(request, "Restore completed.")
        return render(request, "reports/import.html", {"result": result})
    except Exception as e:
        messages.error(request, f"Restore failed: {e}")
        return redirect("reports:drive_backups")


@login_required
def drive_connect(request):
    request.session["drive_connect_next"] = reverse("reports:drive_backups")
    return HttpResponseRedirect("/accounts/google/login/?process=connect")

@login_required
def drive_disconnect(request):
    disconnect_drive(request.user)
    messages.success(request, "Google Drive disconnected.")
    return redirect("reports:drive_backups")
