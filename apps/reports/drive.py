from __future__ import annotations

import io
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload
from typing import Optional
from googleapiclient.errors import HttpError

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/drive.file"


@dataclass(frozen=True)
class DriveFile:
    file_id: str
    name: str
    mime_type: str


def get_drive_status(user) -> dict:
    acc = SocialAccount.objects.filter(user=user, provider="google").first()
    if not acc:
        return {"connected": False, "has_refresh_token": False}

    tok = SocialToken.objects.filter(account=acc).first()
    if not tok:
        return {"connected": True, "has_refresh_token": False}

    refresh = (tok.token_secret or "").strip()
    return {"connected": True, "has_refresh_token": bool(refresh)}


def _credentials_from_allauth(user) -> Credentials:
    acc = SocialAccount.objects.filter(user=user, provider="google").first()
    if not acc:
        raise PermissionDenied("Google account is not connected.")

    tok = SocialToken.objects.filter(account=acc).select_related("app").first()
    if not tok:
        raise PermissionDenied("Google token not found. Reconnect Google Drive.")

    app = tok.app or SocialApp.objects.filter(provider="google").first()
    if not app:
        raise PermissionDenied("Google SocialApp is not configured.")

    access_token = tok.token
    refresh_token = (tok.token_secret or "").strip() or None

    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=app.client_id,
        client_secret=app.secret,
        scopes=[SCOPE],
    )


def _service(user):
    return build("drive", "v3", credentials=_credentials_from_allauth(user))


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
    """
    Returns folder_id where backups should be stored.
    - root_name is created in My Drive root.
    - if subfolder is provided -> creates it inside root_name.
    """
    service = _service(user)
    root_id = get_or_create_folder(service, root_name, parent_id=None)  #

    if subfolder:
        return get_or_create_folder(service, subfolder, parent_id=root_id)

    return root_id


def upload_backup(
    user,
    filename: str,
    content_bytes: bytes,
    mime_type: str,
    root_name: str = "JobApply",
    subfolder: str | None = "backups",
) -> DriveFile:
    service = _service(user)
    folder_id = ensure_jobapply_folder(user, root_name=root_name, subfolder=subfolder)

    media = MediaInMemoryUpload(content_bytes, mimetype=mime_type, resumable=False)
    meta = {"name": filename, "parents": [folder_id]}

    created = service.files().create(body=meta, media_body=media, fields="id,name,mimeType").execute()
    return DriveFile(file_id=created["id"], name=created["name"], mime_type=created["mimeType"])


def list_backups(
    user,
    limit: int = 30,
    root_name: str = "JobApply",
    subfolder: str | None = "backups",
) -> list[DriveFile]:
    service = _service(user)
    folder_id = ensure_jobapply_folder(user, root_name=root_name, subfolder=subfolder)

    res = service.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        orderBy="createdTime desc",
        pageSize=limit,
        fields="files(id,name,mimeType)",
    ).execute()

    return [DriveFile(file_id=f["id"], name=f["name"], mime_type=f["mimeType"]) for f in res.get("files", [])]


def download_file(user, file_id: str) -> bytes:
    service = _service(user)

    req = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    return buf.getvalue()

from allauth.socialaccount.models import SocialAccount, SocialToken


def disconnect_drive(user) -> None:
    """
    Removes stored allauth tokens for Google (access/refresh).
    """
    acc = SocialAccount.objects.filter(user=user, provider="google").first()
    if not acc:
        return
    SocialToken.objects.filter(account=acc).delete()

def _find_file_in_folder_by_name(service, folder_id: str, name: str) -> Optional[str]:
    q = (
        f"'{folder_id}' in parents and trashed=false "
        f"and name='{name}'"
    )
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
    """
    Uploads a new backup as 'latest.<ext>' and keeps only 3 backups in Drive:
      - latest.<ext>
      - backup-1.<ext>
      - backup-2.<ext>

    Rotation:
      backup-2 <- deleted
      backup-1 -> backup-2
      latest   -> backup-1
      new      -> latest
    """
    service = _service(user)
    folder_id = ensure_jobapply_folder(user, root_name=root_name, subfolder=subfolder)

    latest_name = f"autobackup_latest.{ext}"
    b1_name = f"autobackup-1.{ext}"
    b2_name = f"autobackup-2.{ext}"

    latest_id = _find_file_in_folder_by_name(service, folder_id, latest_name)
    b1_id = _find_file_in_folder_by_name(service, folder_id, b1_name)
    b2_id = _find_file_in_folder_by_name(service, folder_id, b2_name)

    if b2_id:
        try:
            _delete_file(service, b2_id)
        except HttpError:
            pass

    if b1_id:
        try:
            _rename_file(service, b1_id, b2_name)
        except HttpError:
            pass

    if latest_id:
        try:
            _rename_file(service, latest_id, b1_name)
        except HttpError:
            pass

    upload_backup(
        user=user,
        filename=latest_name,
        content_bytes=content_bytes,
        mime_type=mime_type,
        root_name=root_name,
        subfolder=subfolder,
    )