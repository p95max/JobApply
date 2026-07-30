from __future__ import annotations

import logging
from datetime import datetime, timezone

from django.db import transaction

from apps.gmail_stats.models import GmailMessage, GmailProcessingStatus, GmailSyncState
from apps.gmail_stats.services.classifier import classify
from apps.gmail_stats.services.direction import determine_direction, parse_recipients, parse_sender
from apps.gmail_stats.services.queries import (
    build_invites_query,
    build_rejections_query,
    build_responses_query,
)

logger = logging.getLogger(__name__)


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


def _candidate_days(*, user, requested_days: int) -> int:
    state = GmailSyncState.objects.filter(user=user).only("last_synced_at").first()
    if not state or not state.last_synced_at:
        return requested_days

    elapsed_seconds = max(0, (datetime.now(timezone.utc) - state.last_synced_at).total_seconds())
    overlap_days = int(elapsed_seconds // 86400) + 3
    return min(requested_days, max(3, overlap_days))


def _save_failed_message(*, user, message_id: str, error: Exception) -> None:
    with transaction.atomic():
        GmailMessage.objects.update_or_create(
            user=user,
            message_id=message_id,
            defaults={
                "thread_id": "",
                "received_at": datetime.now(timezone.utc),
                "processing_status": GmailProcessingStatus.FAILED,
                "processing_error": str(error)[:1000],
            },
        )


def sync_gmail_messages_for_user(*, user, gmail_client, days: int = 180, max_results_each: int = 500) -> dict:
    """
    Pulls candidate emails from Gmail and stores them to DB.
    Returns summary counters.
    """
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")

    candidate_days = _candidate_days(user=user, requested_days=days)
    q_responses = build_responses_query(candidate_days)
    q_rejections = build_rejections_query(candidate_days)
    q_invites = build_invites_query(candidate_days)

    ids: set[str] = set()
    ids.update(gmail_client.list_message_ids(q_responses, max_results=max_results_each))
    ids.update(gmail_client.list_message_ids(q_rejections, max_results=max_results_each))
    ids.update(gmail_client.list_message_ids(q_invites, max_results=max_results_each))

    existing = set(
        GmailMessage.objects.filter(user=user, message_id__in=list(ids))
        .exclude(processing_status=GmailProcessingStatus.FAILED)
        .values_list("message_id", flat=True)
    )

    to_fetch = [mid for mid in ids if mid not in existing]

    created = 0
    failed = 0
    profile_email = gmail_client.get_profile_email()
    for mid in to_fetch:
        try:
            raw = gmail_client.get_message_minimal(mid)

            payload = raw.get("payload") or {}
            headers = payload.get("headers") or []

            subject = _extract_header(headers, "Subject")
            from_header = _extract_header(headers, "From")
            from_name, from_email = parse_sender(from_header)
            to_emails = parse_recipients(
                [
                    _extract_header(headers, "To"),
                    _extract_header(headers, "Cc"),
                    _extract_header(headers, "Delivered-To"),
                ]
            )
            direction = determine_direction(
                from_email=from_email,
                recipient_emails=to_emails,
                profile_email=profile_email,
            )

            snippet = raw.get("snippet") or ""
            received_at = _internal_date_to_dt(raw.get("internalDate"))
            thread_id = raw.get("threadId") or ""

            classified = classify(subject=subject, snippet=snippet)

            with transaction.atomic():
                _, was_created = GmailMessage.objects.update_or_create(
                    user=user,
                    message_id=mid,
                    defaults={
                        "thread_id": thread_id,
                        "direction": direction,
                        "received_at": received_at,
                        "from_name": from_name,
                        "from_email": from_email,
                        "to_emails": to_emails,
                        "subject": subject[:500],
                        "snippet": snippet,
                        "processing_status": GmailProcessingStatus.NEW,
                        "processing_error": "",
                        "detected_type": classified.detected_type,
                        "confidence": classified.confidence,
                    },
                )
            created += int(was_created)
        except (RuntimeError, TypeError, ValueError, AttributeError) as error:
            logger.warning("Gmail message sync failed message_id=%s error=%s", mid, type(error).__name__)
            _save_failed_message(user=user, message_id=mid, error=error)
            failed += 1

    with transaction.atomic():
        state, _ = GmailSyncState.objects.get_or_create(user=user)
        state.last_synced_at = datetime.now(timezone.utc)
        state.save(update_fields=["last_synced_at"])

    return {
        "days": candidate_days,
        "fetched_candidates": len(ids),
        "created": created,
        "skipped_existing": len(existing),
        "failed": failed,
    }
