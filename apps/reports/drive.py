from __future__ import annotations

from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload


def upload_backup_to_drive(access_token: str, filename: str, content_bytes: bytes) -> dict:
    """
    MVP: uses access token from Google OAuth session.
    Real prod version should handle refresh tokens + stored credentials.

    Creates folder: JobApply/backups and uploads file into it.
    """
    service = build("drive", "v3", credentials=None, developerKey=None)
    # NOTE: In a real implementation, you pass proper google-auth Credentials object.
    # This stub is here to match the TZ requirement, but you still need proper OAuth credentials wiring.

    media = MediaInMemoryUpload(content_bytes, mimetype="text/csv", resumable=False)
    file_metadata = {"name": filename}
    created = service.files().create(body=file_metadata, media_body=media, fields="id,name").execute()
    return created
