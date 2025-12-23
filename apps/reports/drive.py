from __future__ import annotations

import io
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/drive.file"


@dataclass(frozen=True)
class DriveFile:
    file_id: str
    name: str
    mime_type: str


def _get_google_account(user) -> SocialAccount:
    acc = SocialAccount.objects.filter(user=user, provider="google").first()
    if not acc:
        raise PermissionDenied("Google account is not connected.")
    return acc


def _get_google_token(account: SocialAccount) -> SocialToken:
    tok = SocialToken.objects.filter(account=account).select_related("app").first()
    if not tok:
        raise PermissionDenied("Google token not found. Reconnect Google Drive.")
    return tok


def get_drive_status(user) -> dict:
    """
    Returns:
      connected: bool
      has_refresh_token: bool
    """
    acc = SocialAccount.objects.filter(user=user, provider="google").first()
    if not acc:
        return {"connected": False, "has_refresh_token": False}

    tok = SocialToken.objects.filter(account=acc).first()
    if not tok:
        return {"connected": True, "has_refresh_token": False}

    refresh = (tok.token_secret or "").strip()
    return {"connected": True, "has_refresh_token": bool(refresh)}


def _credentials_from_allauth(user) -> Credentials:
    account = _get_google_account(user)
    token = _get_google_token(account)

    app = token.app or SocialApp.objects.filter(provider="google").first()
    if not app:
        raise PermissionDenied("Google SocialApp is not configured.")

    access_token = token.token
    refresh_token = (token.token_secret or "").strip() or None

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=app.client_id,
        client_secret=app.secret,
        scopes=[SCOPE],
    )
    return creds


def _service(user):
    creds = _credentials_from_allauth(user)
    return build("drive", "v3", credentials=creds)


def _find_or_create_folder(service, name: str, parent_id: str | None = None) -> str:
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"

    res = service.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    created = service.files().create(body=meta, fields="id").execute()
    return created["id"]


def upload_backup(user, filename: str, content_bytes: bytes, mime_type: str) -> DriveFile:
    service = _service(user)

    root_id = _find_or_create_folder(service, "JobApply")
    backups_id = _find_or_create_folder(service, "backups", parent_id=root_id)

    media = MediaInMemoryUpload(content_bytes, mimetype=mime_type, resumable=False)
    meta = {"name": filename, "parents": [backups_id]}

    created = service.files().create(body=meta, media_body=media, fields="id,name,mimeType").execute()
    return DriveFile(file_id=created["id"], name=created["name"], mime_type=created["mimeType"])


def list_backups(user, limit: int = 30) -> list[DriveFile]:
    service = _service(user)

    root_id = _find_or_create_folder(service, "JobApply")
    backups_id = _find_or_create_folder(service, "backups", parent_id=root_id)

    res = service.files().list(
        q=f"'{backups_id}' in parents and trashed=false",
        orderBy="createdTime desc",
        pageSize=limit,
        fields="files(id,name,mimeType)",
    ).execute()

    out: list[DriveFile] = []
    for f in res.get("files", []):
        out.append(DriveFile(file_id=f["id"], name=f["name"], mime_type=f["mimeType"]))
    return out


def download_file(user, file_id: str) -> bytes:
    service = _service(user)

    req = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, req)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    return buf.getvalue()


def disconnect_drive(user) -> None:
    """
    Removes stored allauth tokens for Google (access/refresh),
    and keeps SocialAccount (optional). You can also delete SocialAccount if you want.
    """
    acc = SocialAccount.objects.filter(user=user, provider="google").first()
    if not acc:
        return
    SocialToken.objects.filter(account=acc).delete()
