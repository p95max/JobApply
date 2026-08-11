from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from google_auth_oauthlib.flow import Flow

from apps.applications.models import JobApplication
from apps.gmail_assistant.models import (
    AnalysisClassifier,
    ApplicationUpdateProposal,
    GmailAnalysis,
    ProposalStatus,
)
from apps.gmail_assistant.services.ai_policy import AIUsagePolicy
from apps.gmail_assistant.services.token_usage import load_token_usage
from apps.security.operation_limits import (
    OperationCooldownError,
    OperationDailyLimitError,
    OperationLimit,
    claim_user_operation,
)

from .drive import (
    DriveError,
    SCOPE as DRIVE_SCOPE,
    TOKEN_URI,
    disconnect_drive,
    download_backup_file,
    ensure_jobapply_folder,
    get_drive_status,
    list_backups,
    upload_backup,
)
from .models import CloudBackupSettings
from .services import (
    ImportValidationError,
    MAX_IMPORT_BYTES,
    build_stats,
    export_csv,
    export_xlsx,
    import_csv,
)

logger = logging.getLogger(__name__)
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
CSV_IMPORT_OPERATION = "csv_import"
DRIVE_MUTATION_OPERATION = "drive_mutation"


def _is_server_operations_owner(user) -> bool:
    owner_email = settings.TELEGRAM_OWNER_EMAIL.strip().casefold()
    user_email = str(getattr(user, "email", "") or "").strip().casefold()
    return bool(owner_email and user_email == owner_email)


def _personal_backup_interval_display() -> str:
    seconds = settings.PERSONAL_DRIVE_BACKUP_INTERVAL_SECONDS
    if seconds % 3600 == 0:
        return f"{seconds // 3600} hours"
    return f"{seconds // 60} minutes"


def _next_personal_backup_at(last_run_at):
    if not last_run_at:
        return None
    return last_run_at + timedelta(seconds=settings.PERSONAL_DRIVE_BACKUP_INTERVAL_SECONDS)


def _claim_csv_import(user) -> None:
    claim_user_operation(
        user=user,
        operation=CSV_IMPORT_OPERATION,
        limit=OperationLimit(
            daily_limit=settings.CSV_IMPORT_DAILY_LIMIT,
            cooldown_seconds=settings.CSV_IMPORT_COOLDOWN_SECONDS,
        ),
    )


def _claim_drive_mutation(user) -> None:
    claim_user_operation(
        user=user,
        operation=DRIVE_MUTATION_OPERATION,
        limit=OperationLimit(
            daily_limit=settings.DRIVE_MANUAL_OPERATION_DAILY_LIMIT,
            cooldown_seconds=settings.DRIVE_MANUAL_OPERATION_COOLDOWN_SECONDS,
        ),
    )


def _operation_limit_message(error: Exception) -> str:
    if isinstance(error, OperationCooldownError):
        return f"Please wait {error.retry_after_seconds} seconds before trying again."
    return "Today's operation limit has been reached. Please try again tomorrow."


def _google_app() -> SocialApp:
    app = SocialApp.objects.filter(provider="google").first()
    if not app:
        raise RuntimeError("Google SocialApp is not configured.")
    return app


def _drive_flow(request, *, state: str | None = None) -> Flow:
    app = _google_app()
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": app.client_id,
                "client_secret": app.secret,
                "auth_uri": GOOGLE_AUTH_URI,
                "token_uri": TOKEN_URI,
            }
        },
        scopes=[DRIVE_SCOPE],
        state=state,
    )
    flow.redirect_uri = request.build_absolute_uri(reverse("reports:drive_callback"))
    return flow


def _fetch_drive_credentials(flow: Flow, authorization_response: str):
    """Complete incremental Google consent while requiring the Drive scope we requested."""
    # Google returns the union of previously granted Gmail/identity scopes and
    # the newly granted Drive scope. oauthlib otherwise rejects that legitimate
    # incremental response as a scope-change warning.
    flow.oauth2session.scope = None
    flow.fetch_token(authorization_response=authorization_response)
    raw_scopes = flow.oauth2session.token.get("scope") or ()
    granted_scopes = set(raw_scopes.split()) if isinstance(raw_scopes, str) else set(raw_scopes)
    if DRIVE_SCOPE not in granted_scopes:
        raise RuntimeError("Google did not grant the required Google Drive permission.")
    return flow.credentials


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
def ai_statistics(request):
    try:
        days = int(request.GET.get("days", "30"))
    except ValueError:
        days = 30
    if days not in {7, 30}:
        days = 30

    since = timezone.now() - timedelta(days=days)
    analyses = GmailAnalysis.objects.filter(user=request.user, analyzed_at__gte=since)
    analysis_totals = analyses.aggregate(
        total=Count("id"),
        ai=Count(
            "id",
            filter=Q(classifier__in=(AnalysisClassifier.AI, AnalysisClassifier.RULE_AI)),
        ),
        rules=Count("id", filter=Q(classifier=AnalysisClassifier.RULE)),
        average_confidence=Avg("confidence"),
    )
    proposals = ApplicationUpdateProposal.objects.filter(
        user=request.user,
        created_at__gte=since,
    )
    proposal_counts = {
        status: proposals.filter(status=status).count()
        for status in ProposalStatus.values
    }
    ai_policy = AIUsagePolicy.from_environment()
    ai_daily_used = ai_policy.daily_usage(user=request.user)

    return render(
        request,
        "reports/ai_statistics.html",
        {
            "days": days,
            "analysis_total": analysis_totals["total"] or 0,
            "analysis_ai": analysis_totals["ai"] or 0,
            "analysis_rules": analysis_totals["rules"] or 0,
            "average_confidence": round(analysis_totals["average_confidence"] or 0),
            "proposal_counts": proposal_counts,
            "token_usage": load_token_usage(user=request.user, days=days),
            "ai_daily_limit": ai_policy.daily_limit,
            "ai_daily_used": ai_daily_used,
            "ai_daily_remaining": max(0, ai_policy.daily_limit - ai_daily_used),
            "ai_model_name": settings.OPENAI_EMAIL_MODEL,
        },
    )


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
@require_http_methods(["GET", "POST"])
def import_view(request):
    if request.method == "POST":
        f = request.FILES.get("file")
        if not f:
            return render(request, "reports/import.html", {"active_tab": "export", "error": "No file uploaded."})
        if f.size > MAX_IMPORT_BYTES:
            return render(request, "reports/import.html", {"active_tab": "export", "error": "The CSV file is too large."})

        try:
            _claim_csv_import(request.user)
            raw = f.read()
            result = import_csv(request.user, raw)
            return render(request, "reports/import.html", {"active_tab": "export", "result": result})
        except (OperationCooldownError, OperationDailyLimitError) as error:
            return render(request, "reports/import.html", {"active_tab": "export", "error": _operation_limit_message(error)})
        except ImportValidationError as error:
            return render(request, "reports/import.html", {"active_tab": "export", "error": str(error)})
        except Exception:
            logger.exception("import_view failed user=%s filename=%s", request.user.id, getattr(f, "name", ""))
            return render(request, "reports/import.html", {"active_tab": "export", "error": "Import failed. Check the file format and try again."})

    return render(request, "reports/import.html", {"active_tab": "export"})


@login_required
def drive_backups(request):
    drive_status = get_drive_status(request.user)

    try:
        settings_obj, _ = CloudBackupSettings.objects.get_or_create(user=request.user)
    except Exception:
        logger.exception("CloudBackupSettings get_or_create failed user=%s", request.user.id)
        settings_obj = CloudBackupSettings(user=request.user, enabled=False, drive_connected=False)

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
            "auto_backup_last_run_at": getattr(settings_obj, "last_run_at", None),
            "auto_backup_next_run_at": _next_personal_backup_at(getattr(settings_obj, "last_run_at", None)),
            "auto_backup_interval_display": _personal_backup_interval_display(),
            "show_server_operations": _is_server_operations_owner(request.user),
            "active_tab": "drive",
        },
    )


@login_required
@require_POST
def drive_export(request, fmt: str):
    if fmt != "csv":
        return redirect("reports:drive_backups")

    qs = JobApplication.objects.filter(user=request.user).order_by("-applied_at")
    ts = timezone.now().strftime("%d-%m-%Y-%H-%M")

    try:
        _claim_drive_mutation(request.user)
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

    except (OperationCooldownError, OperationDailyLimitError) as error:
        messages.error(request, _operation_limit_message(error))
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
@require_POST
def drive_restore(request, file_id: str):
    try:
        _claim_drive_mutation(request.user)
        raw = download_backup_file(request.user, file_id)
        result = import_csv(request.user, raw)
        messages.success(request, "Restore completed.")
        return render(request, "reports/import.html", {"active_tab": "export", "result": result})
    except (OperationCooldownError, OperationDailyLimitError) as error:
        messages.error(request, _operation_limit_message(error))
        return redirect("reports:drive_backups")
    except DriveError as e:
        logger.exception("drive_restore DriveError user=%s code=%s file_id=%s", request.user.id, getattr(e, "code", ""), file_id)
        messages.error(request, str(e))
        return redirect("reports:drive_backups")
    except ImportValidationError as error:
        messages.error(request, str(error))
        return redirect("reports:drive_backups")
    except Exception:
        logger.exception("drive_restore failed user=%s file_id=%s", request.user.id, file_id)
        messages.error(request, "Restore failed. Check the backup file and try again.")
        return redirect("reports:drive_backups")


@login_required
def drive_connect(request):
    try:
        flow = _drive_flow(request)
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        request.session["drive_oauth_state"] = state
        return HttpResponseRedirect(authorization_url)
    except Exception:
        logger.exception("drive_connect failed user=%s", request.user.id)
        messages.error(request, "Could not start Google Drive authorization. Try again later.")
        return redirect("reports:drive_backups")


@login_required
def drive_callback(request):
    if request.GET.get("error"):
        messages.info(request, "Google Drive access was not granted.")
        return redirect("reports:drive_backups")

    state = request.session.pop("drive_oauth_state", "")
    if not state or request.GET.get("state") != state:
        messages.error(request, "Google Drive authorization expired. Please try again.")
        return redirect("reports:drive_backups")

    try:
        flow = _drive_flow(request, state=state)
        credentials = _fetch_drive_credentials(flow, request.build_absolute_uri())

        account = SocialAccount.objects.filter(user=request.user, provider="google").first()
        if not account:
            raise RuntimeError("Google account is not connected.")
        app = _google_app()
        token, _ = SocialToken.objects.get_or_create(account=account, app=app)
        token.token = credentials.token or token.token
        if credentials.refresh_token:
            token.token_secret = credentials.refresh_token
        token.expires_at = credentials.expiry
        token.save()

        settings_obj, _ = CloudBackupSettings.objects.get_or_create(user=request.user)
        settings_obj.drive_connected = True
        settings_obj.enabled = False
        settings_obj.save(update_fields=["drive_connected", "enabled", "updated_at"])
        messages.success(request, "Google Drive connected. Automatic backups remain off until you enable them.")
    except Exception:
        logger.exception("drive_callback failed user=%s", request.user.id)
        messages.error(request, "Google Drive connection failed. Please try again.")

    return redirect("reports:drive_backups")


@login_required
@require_POST
def drive_disconnect(request):
    try:
        disconnect_drive(request.user)
        messages.success(request, "Google Drive backups disabled. Your Google sign-in remains connected.")
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
        messages.error(request, "Connect Google Drive before enabling automatic backups.")
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
        messages.success(
            request,
            f"Automatic backups enabled (every {_personal_backup_interval_display()}).",
        )
    else:
        messages.success(request, "Automatic backups disabled.")

    return redirect("reports:drive_backups")
