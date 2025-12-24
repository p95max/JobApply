from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from allauth.socialaccount.models import SocialAccount

from apps.applications.models import JobApplication

from .drive import (
    DriveError,
    disconnect_drive,
    download_file,
    ensure_jobapply_folder,
    get_drive_status,
    list_backups,
    upload_backup,
)
from .models import CloudBackupSettings
from .services import build_stats, export_csv, export_xlsx, import_csv

logger = logging.getLogger(__name__)


@login_required
def statistics(request):
    try:
        qs = JobApplication.objects.filter(user=request.user)
        stats = build_stats(qs)
        return render(request, "reports/statistics.html", {"stats": stats})
    except Exception:
        logger.exception("statistics failed user=%s", request.user.id)
        messages.error(request, "Could not build statistics. Try again later.")
        return render(request, "reports/statistics.html", {"stats": {}})


@login_required
def export_report(request, fmt: str):
    qs = JobApplication.objects.filter(user=request.user)

    try:
        if fmt == "csv":
            content = export_csv(qs)
            resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
            resp["Content-Disposition"] = 'attachment; filename="jobapply_export.csv"'
            return resp

        if fmt == "xlsx":
            content = export_xlsx(qs)
            resp = HttpResponse(
                content,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            resp["Content-Disposition"] = 'attachment; filename="jobapply_export.xlsx"'
            return resp

        return redirect("reports:statistics")
    except Exception:
        logger.exception("export_report failed fmt=%s user=%s", fmt, request.user.id)
        messages.error(request, "Export failed. Try again later.")
        return redirect("reports:statistics")


@login_required
def import_view(request):
    if request.method == "POST":
        f = request.FILES.get("file")
        if not f:
            return render(request, "reports/import.html", {"error": "No file uploaded."})

        try:
            raw = f.read()
            result = import_csv(request.user, raw)
            return render(request, "reports/import.html", {"result": result})
        except Exception:
            logger.exception("import_view failed user=%s filename=%s", request.user.id, getattr(f, "name", ""))
            return render(request, "reports/import.html", {"error": "Import failed. Check the file format and try again."})

    return render(request, "reports/import.html")


@login_required
def drive_backups(request):
    drive_status = get_drive_status(request.user)

    try:
        settings_obj, _ = CloudBackupSettings.objects.get_or_create(user=request.user)
    except Exception:
        logger.exception("CloudBackupSettings get_or_create failed user=%s", request.user.id)
        settings_obj = CloudBackupSettings(user=request.user, enabled=False)

    google_email = None
    folder_url = None

    try:
        acc = SocialAccount.objects.filter(user=request.user, provider="google").first()
        if acc:
            google_email = (request.user.email or "") or (acc.extra_data.get("email") if acc.extra_data else None)
    except Exception:
        logger.exception("drive_backups google_email resolve failed user=%s", request.user.id)

    backups: list = []
    error = None

    if drive_status.get("connected") and drive_status.get("has_refresh_token"):
        try:
            folder_id = ensure_jobapply_folder(
                request.user,
                root_name="JobApply",
                subfolder="backups",
            )
            folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
            backups = list_backups(request.user, limit=30, root_name="JobApply", subfolder="backups")
        except DriveError as e:
            logger.exception("drive_backups DriveError user=%s code=%s", request.user.id, getattr(e, "code", ""))
            error = str(e)
        except Exception:
            logger.exception("drive_backups failed user=%s", request.user.id)
            error = "Could not load Google Drive backups. Try again later."

    return render(
        request,
        "reports/drive_backups.html",
        {
            "drive_status": drive_status,
            "google_email": google_email,
            "folder_url": folder_url,
            "backups": backups,
            "error": error,
            "auto_backup_enabled": bool(getattr(settings_obj, "enabled", False)),
        },
    )


@login_required
def drive_export(request, fmt: str):
    if fmt != "csv":
        return redirect("reports:drive_backups")

    qs = JobApplication.objects.filter(user=request.user).order_by("-applied_at")
    ts = timezone.now().strftime("%d-%m-%Y-%H-%M")

    try:
        content = export_csv(qs)
        filename = f"manual_backup-{ts}.csv"

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

    except DriveError as e:
        logger.exception("drive_export DriveError user=%s code=%s", request.user.id, getattr(e, "code", ""))
        messages.error(request, str(e))
        return redirect("reports:drive_backups")
    except Exception:
        logger.exception("drive_export failed user=%s", request.user.id)
        messages.error(request, "Drive export failed. Try again later.")
        return redirect("reports:drive_backups")


@login_required
def drive_restore(request, file_id: str):
    try:
        raw = download_file(request.user, file_id)
        result = import_csv(request.user, raw)
        messages.success(request, "Restore completed.")
        return render(request, "reports/import.html", {"result": result})
    except DriveError as e:
        logger.exception("drive_restore DriveError user=%s code=%s file_id=%s", request.user.id, getattr(e, "code", ""), file_id)
        messages.error(request, str(e))
        return redirect("reports:drive_backups")
    except Exception:
        logger.exception("drive_restore failed user=%s file_id=%s", request.user.id, file_id)
        messages.error(request, "Restore failed. Check the backup file and try again.")
        return redirect("reports:drive_backups")


@login_required
def drive_connect(request):
    try:
        request.session["drive_connect_next"] = reverse("reports:drive_backups")
    except Exception:
        logger.exception("drive_connect session set failed user=%s", request.user.id)
    return HttpResponseRedirect("/accounts/google/login/?process=connect")


@login_required
def drive_disconnect(request):
    try:
        disconnect_drive(request.user)
        messages.success(request, "Google Drive disconnected.")
    except Exception:
        logger.exception("drive_disconnect failed user=%s", request.user.id)
        messages.error(request, "Could not disconnect Google Drive. Try again.")
    return redirect("reports:drive_backups")


@login_required
@require_POST
def toggle_auto_backup(request):
    drive_status = get_drive_status(request.user)

    enabled = request.POST.get("enabled") == "1"

    if enabled and not (drive_status.get("connected") and drive_status.get("has_refresh_token")):
        messages.error(request, "Connect Google Drive (offline access) before enabling auto backups.")
        return redirect("reports:drive_backups")

    try:
        settings_obj, _ = CloudBackupSettings.objects.get_or_create(user=request.user)
        settings_obj.enabled = enabled
        settings_obj.save(update_fields=["enabled", "updated_at"])
    except Exception:
        logger.exception("toggle_auto_backup save failed user=%s enabled=%s", request.user.id, enabled)
        messages.error(request, "Could not update auto backup setting. Try again later.")
        return redirect("reports:drive_backups")

    if enabled:
        messages.success(request, "Auto backups enabled (every 5 minutes).")
    else:
        messages.success(request, "Auto backups disabled.")

    return redirect("reports:drive_backups")
