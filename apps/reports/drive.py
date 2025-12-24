from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload

try:
    from google.auth.exceptions import RefreshError
except Exception:
    RefreshError = Exception

logger = logging.getLogger(__name__)

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/drive.file"


class DriveError(RuntimeError):
    def __init__(self, message: str, *, code: str = "drive_error"):
        super().__init__(message)
        self.code = code


def _friendly_http_error(err: HttpError) -> DriveError:
    status = getattr(getattr(err, "resp", None), "status", None)

    if status in (401, 403):
        return DriveError(
            "Google Drive access was denied or expired. Please reconnect Google Drive.",
            code="auth",
        )
    if status == 404:
        return DriveError("Drive folder/file was not found. Try reconnecting.", code="not_found")
    if status == 429:
        return DriveError("Google Drive quota/rate limit hit. Try again later.", code="rate_limited")
    if status and 500 <= status <= 599:
        return DriveError("Google Drive is temporarily unavailable. Try again later.", code="upstream")

    return DriveError(f"Google Drive error: {err}", code="http_error")


def _wrap_drive_call(action: str, fn):
    try:
        return fn()
    except PermissionDenied:
        raise
    except RefreshError as e:
        logger.exception("Drive refresh error during %s", action)
        raise DriveError("Google session expired. Reconnect Google Drive.", code="refresh") from e
    except HttpError as e:
        logger.exception("Drive HttpError during %s", action)
        raise _friendly_http_error(e) from e
    except Exception as e:
        logger.exception("Drive unexpected error during %s", action)
        raise DriveError("Unexpected Google Drive error. Try again later.", code="unexpected") from e


@dataclass(frozen=True)
class DriveFile:
    file_id: str
    name: str
    mime_type: str


def get_drive_status(user) -> dict:
    def _do():
        acc = SocialAccount.objects.filter(user=user, provider="google").first()
        if not acc:
            return {"connected": False, "has_refresh_token": False}

        tok = SocialToken.objects.filter(account=acc).first()
        if not tok:
            return {"connected": True, "has_refresh_token": False}

        refresh = (tok.token_secret or "").strip()
        return {"connected": True, "has_refresh_token": bool(refresh)}

    try:
        return _do()
    except Exception:
        logger.exception("get_drive_status failed")
        return {"connected": False, "has_refresh_token": False, "error": "Drive status check failed"}


def _credentials_from_allauth(user) -> Credentials:
    acc = SocialAccount.objects.filter(user=user, provider="google").first()
    if not acc:
        raise PermissionDenied("Google account is not connected.")

    tok = SocialToken.objects.filter(account=acc).select_related("app").first()
    if not tok:
        raise PermissionDenied("Google token not found. Reconnect Google Drive.")

    app = tok.app
    if not app:
        app = SocialApp.objects.filter(provider="google").first()
    if not app:
        raise PermissionDenied("Google SocialApp is not configured.")

    access_token = tok.token
    refresh_token = (tok.token_secret or "").strip() or None
    if not refresh_token:
        raise PermissionDenied("Google refresh token is missing. Reconnect Google Drive.")

    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=app.client_id,
        client_secret=app.secret,
        scopes=[SCOPE],
    )


def _service(user):
    def _do():
        creds = _credentials_from_allauth(user)
        return build("drive", "v3", credentials=creds)

    return _wrap_drive_call("_service", _do)


def _find_folder(service, name: str, parent_id: str | None) -> str | None:
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"

    res = service.files().list(q=q, fields="files(id,name)", pageSize=1).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _create_folder(service, name: str, parent_id: str | None) -> str:
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    created = service.files().create(body=meta, fields="id").execute()
    return created["id"]


def get_or_create_folder(service, name: str, parent_id: str | None = None) -> str:
    folder_id = _find_folder(service, name=name, parent_id=parent_id)
    if folder_id:
        return folder_id
    return _create_folder(service, name=name, parent_id=parent_id)


def ensure_jobapply_folder(user, root_name: str = "JobApply", subfolder: str | None = "backups") -> str:
    def _do():
        service = _service(user)
        root_id = get_or_create_folder(service, root_name, parent_id=None)
        if subfolder:
            return get_or_create_folder(service, subfolder, parent_id=root_id)
        return root_id

    return _wrap_drive_call("ensure_jobapply_folder", _do)


def upload_backup(
    user,
    filename: str,
    content_bytes: bytes,
    mime_type: str,
    root_name: str = "JobApply",
    subfolder: str | None = "backups",
) -> DriveFile:
    def _do():
        service = _service(user)
        folder_id = ensure_jobapply_folder(user, root_name=root_name, subfolder=subfolder)
        media = MediaInMemoryUpload(content_bytes, mimetype=mime_type, resumable=False)
        meta = {"name": filename, "parents": [folder_id]}
        created = service.files().create(body=meta, media_body=media, fields="id,name,mimeType").execute()
        return DriveFile(file_id=created["id"], name=created["name"], mime_type=created["mimeType"])

    return _wrap_drive_call("upload_backup", _do)


def list_backups(
    user,
    limit: int = 30,
    root_name: str = "JobApply",
    subfolder: str | None = "backups",
) -> list[DriveFile]:
    def _do():
        service = _service(user)
        folder_id = ensure_jobapply_folder(user, root_name=root_name, subfolder=subfolder)
        res = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            orderBy="createdTime desc",
            pageSize=limit,
            fields="files(id,name,mimeType)",
        ).execute()
        return [DriveFile(file_id=f["id"], name=f["name"], mime_type=f["mimeType"]) for f in res.get("files", [])]

    return _wrap_drive_call("list_backups", _do)


def download_file(user, file_id: str) -> bytes:
    def _do():
        service = _service(user)
        req = service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    return _wrap_drive_call("download_file", _do)


def disconnect_drive(user) -> None:
    acc = SocialAccount.objects.filter(user=user, provider="google").first()
    if not acc:
        return
    SocialToken.objects.filter(account=acc).delete()


def _find_file_in_folder_by_name(service, folder_id: str, name: str) -> str | None:
    q = f"'{folder_id}' in parents and trashed=false and name='{name}'"
    res = service.files().list(q=q, fields="files(id,name)", pageSize=1).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _rename_file(service, file_id: str, new_name: str) -> None:
    service.files().update(fileId=file_id, body={"name": new_name}).execute()


def _delete_file(service, file_id: str) -> None:
    service.files().delete(fileId=file_id).execute()


def upload_backup_rotate_3(
    user,
    content_bytes: bytes,
    mime_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ext: str = "csv",
    root_name: str = "JobApply",
    subfolder: str | None = "backups",
) -> None:
    def _do():
        def safe(action, fn):
            try:
                fn()
            except (HttpError, RefreshError, DriveError):
                logger.exception("Drive rotate step failed: %s", action)

        service = _service(user)
        folder_id = ensure_jobapply_folder(user, root_name=root_name, subfolder=subfolder)

        latest_name = f"autobackup_latest.{ext}"
        b1_name = f"autobackup-1.{ext}"
        b2_name = f"autobackup-2.{ext}"

        latest_id = _find_file_in_folder_by_name(service, folder_id, latest_name)
        b1_id = _find_file_in_folder_by_name(service, folder_id, b1_name)
        b2_id = _find_file_in_folder_by_name(service, folder_id, b2_name)

        if b2_id:
            safe("delete backup-2", lambda: _delete_file(service, b2_id))
        if b1_id:
            safe("rename backup-1 -> backup-2", lambda: _rename_file(service, b1_id, b2_name))
        if latest_id:
            safe("rename latest -> backup-1", lambda: _rename_file(service, latest_id, b1_name))

        upload_backup(
            user=user,
            filename=latest_name,
            content_bytes=content_bytes,
            mime_type=mime_type,
            root_name=root_name,
            subfolder=subfolder,
        )

    return _wrap_drive_call("upload_backup_rotate_3", _do)
