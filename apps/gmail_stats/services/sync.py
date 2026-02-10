from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from django.db import transaction
from django.utils.dateparse import parse_datetime

from apps.gmail_stats.models import GmailMessage, GmailSyncState
from apps.gmail_stats.services.classifier import classify
from apps.gmail_stats.services.queries import (
    build_invites_query,
    build_rejections_query,
    build_responses_query,
)


def _extract_header(headers: list[dict], name: str) -> str:
    name_low = name.lower()
    for h in headers or []:
        if (h.get("name") or "").lower() == name_low:
            return h.get("value") or ""
    return ""


def _internal_date_to_dt(internal_date_ms: str | int | None) -> datetime:
    if internal_date_ms is None:
        return datetime.now(timezone.utc)
    ms = int(internal_date_ms)
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def sync_gmail_messages_for_user(*, user, gmail_client, days: int = 180, max_results_each: int = 500) -> dict:
    """
    Pulls candidate emails from Gmail and stores them to DB.
    Returns summary counters.
    """
    q_responses = build_responses_query(days)
    q_rejections = build_rejections_query(days)
    q_invites = build_invites_query(days)

    ids: set[str] = set()
    ids.update(gmail_client.list_message_ids(q_responses, max_results=max_results_each))
    ids.update(gmail_client.list_message_ids(q_rejections, max_results=max_results_each))
    ids.update(gmail_client.list_message_ids(q_invites, max_results=max_results_each))

    existing = set(
        GmailMessage.objects.filter(message_id__in=list(ids)).values_list("message_id", flat=True)
    )

    to_fetch = [mid for mid in ids if mid not in existing]

    created = 0
    with transaction.atomic():
        for mid in to_fetch:
            raw = gmail_client.get_message_minimal(mid)

            payload = raw.get("payload") or {}
            headers = payload.get("headers") or []

            subject = _extract_header(headers, "Subject")
            from_header = _extract_header(headers, "From")

            from_email = ""
            if "<" in from_header and ">" in from_header:
                from_email = from_header.split("<", 1)[1].split(">", 1)[0].strip()
            else:
                from_email = from_header.strip()

            snippet = raw.get("snippet") or ""
            received_at = _internal_date_to_dt(raw.get("internalDate"))
            thread_id = raw.get("threadId") or ""

            classified = classify(subject=subject, snippet=snippet)

            GmailMessage.objects.create(
                user=user,
                message_id=mid,
                thread_id=thread_id,
                received_at=received_at,
                from_email=from_email[:254],
                subject=subject[:500],
                snippet=snippet,
                detected_type=classified.detected_type,
                confidence=classified.confidence,
            )
            created += 1

        state, _ = GmailSyncState.objects.get_or_create(user=user)
        state.last_synced_at = datetime.now(timezone.utc)
        state.save(update_fields=["last_synced_at"])

    return {
        "days": days,
        "fetched_candidates": len(ids),
        "created": created,
        "skipped_existing": len(existing),
    }
