from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from django.db import DatabaseError, transaction
from django.utils import timezone as django_timezone

from apps.gmail_stats.models import (
    AnalysisClassifier,
    GmailAnalysis,
    GmailAssistantSettings,
    GmailDirection,
    GmailMessage,
    GmailProcessingStatus,
    GmailSyncState,
)
from apps.gmail_stats.services.ai_analyzer import (
    AIAnalysisContext,
    AIAnalyzerError,
    AIAnalyzerConfig,
    OpenAIEmailAnalyzer,
    SanitizedEmail,
)
from apps.gmail_stats.services.application_matcher import match_for_message
from apps.gmail_stats.services.classifier import RuleClassification, classify_event
from apps.gmail_stats.services.direction import determine_direction
from apps.gmail_stats.services.message_parser import ParsedGmailMessage, parse_gmail_message
from apps.gmail_stats.services.proposal_builder import build_proposals
from apps.gmail_stats.services.queries import build_candidate_query

logger = logging.getLogger(__name__)


def _internal_date_to_dt(internal_date_ms: str | int | None) -> datetime:
    if internal_date_ms is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(int(internal_date_ms) / 1000.0, tz=timezone.utc)


def _candidate_days(*, user: Any, requested_days: int) -> int:
    state = GmailSyncState.objects.filter(user=user).only("last_synced_at").first()
    if not state or not state.last_synced_at:
        return requested_days
    elapsed_seconds = max(0, (datetime.now(timezone.utc) - state.last_synced_at).total_seconds())
    overlap_days = int(elapsed_seconds // 86400) + 3
    return min(requested_days, max(3, overlap_days))


def _save_failed_message(*, user: Any, message_id: str, error: Exception) -> None:
    with transaction.atomic():
        GmailMessage.objects.update_or_create(
            user=user,
            message_id=message_id,
            defaults={
                "thread_id": "",
                "received_at": datetime.now(timezone.utc),
                "processing_status": GmailProcessingStatus.FAILED,
                "processing_error": type(error).__name__,
            },
        )


def _store_message(
    *,
    user: Any,
    message_id: str,
    raw: dict[str, Any],
    parsed: ParsedGmailMessage,
    direction: str,
    rule: RuleClassification,
) -> tuple[GmailMessage, bool]:
    with transaction.atomic():
        return GmailMessage.objects.update_or_create(
            user=user,
            message_id=message_id,
            defaults={
                "thread_id": str(raw.get("threadId") or ""),
                "direction": direction,
                "received_at": _internal_date_to_dt(raw.get("internalDate")),
                "from_name": parsed.from_name,
                "from_email": parsed.from_email,
                "to_emails": parsed.to_emails,
                "subject": parsed.subject,
                "snippet": str(raw.get("snippet") or "")[:1000],
                "content_hash": parsed.content_hash,
                "processing_status": GmailProcessingStatus.PARSED,
                "processing_error": "",
                "detected_type": rule.detected_type,
                "confidence": rule.confidence,
            },
        )


def _record_analysis(
    *,
    user: Any,
    message: GmailMessage,
    rule: RuleClassification,
    classifier: str,
    extracted_data: dict[str, Any],
    event_type: str | None = None,
    confidence: int | None = None,
    is_job_related: bool | None = None,
    model_name: str = "",
) -> GmailAnalysis:
    with transaction.atomic():
        analysis, _ = GmailAnalysis.objects.update_or_create(
            user=user,
            message=message,
            defaults={
                "event_type": event_type or rule.event_type,
                "is_job_related": rule.is_job_related if is_job_related is None else is_job_related,
                "classifier": classifier,
                "confidence": confidence if confidence is not None else rule.confidence,
                "extracted_data": extracted_data,
                "model_name": model_name,
                "prompt_version": "v1",
                "schema_version": "v1",
                "analyzed_at": django_timezone.now(),
            },
        )
    return analysis


def _rule_data(rule: RuleClassification) -> dict[str, Any]:
    return {"evidence": list(rule.evidence)}


def _ai_data(result: Any) -> dict[str, Any]:
    interview = None
    if result.interview:
        interview = {
            "starts_at": result.interview.starts_at,
            "ends_at": result.interview.ends_at,
            "timezone": result.interview.timezone,
            "mode": result.interview.mode,
            "location": result.interview.location,
            "meeting_url": result.interview.meeting_url,
        }
    return {
        "company": result.company,
        "position_title": result.position_title,
        "external_application_id": result.external_application_id,
        "recruiter_name": result.recruiter_name,
        "recruiter_email": result.recruiter_email,
        "summary": result.summary,
        "action_required": result.action_required,
        "action_text": result.action_text,
        "deadline_at": result.deadline_at,
        "interview": interview,
        "evidence": list(result.evidence),
    }


def _should_use_ai(*, rule: RuleClassification, ai_enabled: bool, config: AIAnalyzerConfig) -> bool:
    return (
        ai_enabled
        and config.enabled
        and bool(config.api_key)
        and rule.event_type != "noise"
        and (rule.is_job_related or rule.confidence < 70)
    )


def _update_message_status(*, message: GmailMessage, status: str, error: str = "") -> None:
    GmailMessage.objects.filter(pk=message.pk).update(
        processing_status=status,
        processing_error=error[:255],
        updated_at=django_timezone.now(),
    )


def _assistant_settings(user: Any) -> GmailAssistantSettings | None:
    return GmailAssistantSettings.objects.filter(user=user).only("ai_enabled").first()


def sync_gmail_messages_for_user(
    *,
    user: Any,
    gmail_client: Any,
    days: int = 180,
    max_results_each: int = 500,
    ai_analyzer: OpenAIEmailAnalyzer | None = None,
) -> dict[str, int]:
    """Run the bounded, per-message Gmail assistant pipeline for one user."""
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")

    candidate_days = _candidate_days(user=user, requested_days=days)
    ids = set(
        gmail_client.list_message_ids(build_candidate_query(candidate_days), max_results=max_results_each)
    )
    existing = set(
        GmailMessage.objects.filter(user=user, message_id__in=ids)
        .exclude(processing_status=GmailProcessingStatus.FAILED)
        .values_list("message_id", flat=True)
    )
    profile_email = gmail_client.get_profile_email()
    settings = _assistant_settings(user)
    config = ai_analyzer.config if ai_analyzer else AIAnalyzerConfig.from_environment()
    analyzer = ai_analyzer or OpenAIEmailAnalyzer(config)
    counters = {
        "days": candidate_days,
        "fetched_candidates": len(ids),
        "candidates": len(ids),
        "created": 0,
        "skipped_existing": len(existing),
        "failed": 0,
        "ignored_noise": 0,
        "outbound_ignored": 0,
        "analyzed_by_rules": 0,
        "analyzed_by_ai": 0,
        "proposals_created": 0,
        "unmatched": 0,
    }

    for message_id in ids - existing:
        try:
            raw = gmail_client.get_message_full(message_id)
            parsed = parse_gmail_message(raw)
            direction = determine_direction(
                from_email=parsed.from_email,
                recipient_emails=parsed.to_emails,
                profile_email=profile_email,
            )
            rule = classify_event(parsed.subject, str(raw.get("snippet") or ""), parsed.text)
            message, created = _store_message(
                user=user,
                message_id=message_id,
                raw=raw,
                parsed=parsed,
                direction=direction,
                rule=rule,
            )
            counters["created"] += int(created)

            if direction == GmailDirection.OUTBOUND:
                _update_message_status(message=message, status=GmailProcessingStatus.IGNORED)
                counters["outbound_ignored"] += 1
                continue

            if rule.event_type == "noise":
                _record_analysis(
                    user=user,
                    message=message,
                    rule=rule,
                    classifier=AnalysisClassifier.RULE,
                    extracted_data=_rule_data(rule),
                )
                _update_message_status(message=message, status=GmailProcessingStatus.IGNORED)
                counters["ignored_noise"] += 1
                counters["analyzed_by_rules"] += 1
                continue

            use_ai = _should_use_ai(
                rule=rule,
                ai_enabled=bool(settings and settings.ai_enabled),
                config=config,
            )
            if use_ai:
                try:
                    result = analyzer.analyze(
                        SanitizedEmail(
                            message_id=message_id,
                            subject=parsed.subject,
                            from_name=parsed.from_name,
                            from_email=parsed.from_email,
                            text=parsed.text,
                        ),
                        AIAnalysisContext(
                            rule_event_type=rule.event_type,
                            rule_confidence=rule.confidence,
                        ),
                    )
                    analysis = _record_analysis(
                        user=user,
                        message=message,
                        rule=rule,
                        classifier=AnalysisClassifier.RULE_AI,
                        extracted_data=_ai_data(result),
                        event_type=result.event_type,
                        confidence=result.confidence,
                        is_job_related=result.is_job_related,
                        model_name=config.model,
                    )
                    counters["analyzed_by_ai"] += 1
                except AIAnalyzerError as error:
                    logger.warning(
                        "Gmail AI analysis failed message_id=%s error=%s",
                        message_id,
                        type(error).__name__,
                    )
                    analysis = _record_analysis(
                        user=user,
                        message=message,
                        rule=rule,
                        classifier=AnalysisClassifier.RULE,
                        extracted_data=_rule_data(rule),
                    )
                    _update_message_status(
                        message=message,
                        status=GmailProcessingStatus.ANALYZED,
                        error=type(error).__name__,
                    )
                    counters["analyzed_by_rules"] += 1
                    continue
            else:
                analysis = _record_analysis(
                    user=user,
                    message=message,
                    rule=rule,
                    classifier=AnalysisClassifier.RULE,
                    extracted_data=_rule_data(rule),
                )
                counters["analyzed_by_rules"] += 1

            match = match_for_message(
                user=user,
                message=message,
                extracted_data=analysis.extracted_data,
            )
            proposals = build_proposals(message=message, analysis=analysis, match=match)
            counters["proposals_created"] += len(proposals)
            counters["unmatched"] += int(match.is_unmatched)
            _update_message_status(
                message=message,
                status=(
                    GmailProcessingStatus.PROPOSAL_CREATED
                    if proposals
                    else GmailProcessingStatus.ANALYZED
                ),
            )
        except (AttributeError, DatabaseError, RuntimeError, TypeError, ValueError) as error:
            logger.warning(
                "Gmail message processing failed message_id=%s error=%s",
                message_id,
                type(error).__name__,
            )
            _save_failed_message(user=user, message_id=message_id, error=error)
            counters["failed"] += 1

    with transaction.atomic():
        state, _ = GmailSyncState.objects.get_or_create(user=user)
        state.last_synced_at = datetime.now(timezone.utc)
        state.save(update_fields=["last_synced_at"])
        if settings:
            settings.last_successful_run_at = django_timezone.now()
            if counters["failed"]:
                settings.last_error_at = django_timezone.now()
                settings.last_error_message = "message_processing_failed"
                settings.save(
                    update_fields=[
                        "last_successful_run_at",
                        "last_error_at",
                        "last_error_message",
                        "updated_at",
                    ]
                )
            else:
                settings.save(update_fields=["last_successful_run_at", "updated_at"])
    return counters
