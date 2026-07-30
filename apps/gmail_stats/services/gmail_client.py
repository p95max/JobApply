from __future__ import annotations

from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class GmailClient:
    def __init__(self, credentials):
        self._svc = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def list_message_ids(self, query: str, max_results: int = 500) -> list[str]:
        """
        Lists message IDs by Gmail search query.
        Note: Gmail returns pages; we iterate until max_results.
        """
        ids: list[str] = []
        page_token = None

        try:
            while True:
                resp = (
                    self._svc.users()
                    .messages()
                    .list(userId="me", q=query, maxResults=min(500, max_results - len(ids)), pageToken=page_token)
                    .execute()
                )
                for m in resp.get("messages", []):
                    ids.append(m["id"])
                    if len(ids) >= max_results:
                        return ids

                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
        except HttpError as e:
            raise RuntimeError(f"Gmail API list failed: {e}") from e

        return ids

    def get_message_minimal(self, message_id: str) -> dict[str, Any]:
        """
        Fetch minimal message info: headers + snippet + internalDate + threadId.
        """
        try:
            msg = (
                self._svc.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=["Subject", "From", "To", "Cc", "Delivered-To", "Date"],
                )
                .execute()
            )
            return msg
        except HttpError as e:
            raise RuntimeError(f"Gmail API get failed (id={message_id}): {e}") from e

    def get_profile_email(self) -> str:
        """Return the email address of the authenticated Gmail mailbox."""
        try:
            profile = self._svc.users().getProfile(userId="me").execute()
            return str(profile.get("emailAddress") or "")
        except HttpError as e:
            raise RuntimeError(f"Gmail API profile failed: {e}") from e
