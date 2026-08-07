from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from django.db import DatabaseError, transaction
from django.utils import timezone as django_timezone

from apps.gmail_assistant.models import AnalysisClassifier, GmailAnalysis, GmailAssistantSettings
from apps.gmail_assistant.services.ai_analyzer import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    AIAnalysisContext,
    AIAnalyzerConfig,
    AIAnalyzerError,
    OpenAIEmailAnalyzer,
    SanitizedEmail,
)
from apps.gmail_assistant.services.ai_policy import AIUsagePolicy, sanitize_email_text
from apps.gmail_assistant.services.application_matcher import match_for_message
from apps.gmail_assistant.services.classifier import RuleClassification, classify_event
from apps.gmail_assistant.services.proposal_builder import build_proposals
from apps.gmail_assistant.services.queries import build_candidate_query, build_sent_applications_query
from apps.gmail_stats.models import GmailDirection, GmailMessage, GmailProcessingStatus, GmailSyncState
from apps.gmail_stats.services.direction import determine_direction
from apps.gmail_stats.services.message_parser import ParsedGmailMessage, parse_gmail_message

logger = logging.getLogger(__name__)

_REPLY_SUBJECT_RE = re.compile(r"^\s*(?:re|aw|fw|fwd)\s*:", re.IGNORECASE)
_DIRECT_APPLICATION_SUBJECT_RE = re.compile(
    r"^\s*(?:(?:initiativ|erneute)\s+)?(?:bewerbung|application)(?:\s+(?:als|for))?\s+(?P<title>.+?)\s*$",
    re.IGNORECASE,
)


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
                "prompt_version": PROMPT_VERSION,
                "schema_version": SCHEMA_VERSION,
                "analyzed_at": django_timezone.now(),
            },
        )
    return analysis


def _rule_data(rule: RuleClassification, *, fallback_reason: str = "") -> dict[str, Any]:
    data: dict[str, Any] = {"evidence": list(rule.evidence)}
    if fallback_reason:
        data["fallback_reason"] = fallback_reason
    return data


def _ai_data(result: Any, *, requires_manual_review: bool) -> dict[str, Any]:
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
        "location": result.location,
        "external_application_id": result.external_application_id,
        "recruiter_name": result.recruiter_name,
        "recruiter_email": result.recruiter_email,
        "summary": result.summary,
        "action_required": result.action_required,
        "action_text": result.action_text,
        "deadline_at": result.deadline_at,
        "interview": interview,
        "evidence": list(result.evidence),
        "requires_manual_review": requires_manual_review,
    }


def _ai_available(*, ai_enabled: bool, config: AIAnalyzerConfig) -> bool:
    return ai_enabled and config.enabled and bool(config.api_key) and bool(config.model)


def _update_message_status(*, message: GmailMessage, status: str, error: str = "") -> None:
    GmailMessage.objects.filter(pk=message.pk).update(
        processing_status=status,
        processing_error=error[:255],
        updated_at=django_timezone.now(),
    )


def _assistant_settings(user: Any) -> GmailAssistantSettings | None:
    return GmailAssistantSettings.objects.filter(user=user).only("ai_enabled").first()


def _record_rule_fallback(
    *,
    user: Any,
    message: GmailMessage,
    rule: RuleClassification,
    reason: str,
    extracted_data: dict[str, Any] | None = None,
) -> GmailAnalysis:
    return _record_analysis(
        user=user,
        message=message,
        rule=rule,
        classifier=AnalysisClassifier.RULE,
        extracted_data=extracted_data or _rule_data(rule, fallback_reason=reason),
    )


def _outbound_application_rule(rule: RuleClassification) -> RuleClassification:
    """Relevant messages from Sent represent an application sent by the user."""
    if not rule.is_job_related:
        return rule
    return RuleClassification(
        event_type="application_sent",
        detected_type=rule.detected_type,
        is_job_related=True,
        confidence=max(rule.confidence, 80),
        evidence=rule.evidence or ("sent by mailbox owner",),
    )


def _is_direct_sent_application(*, subject: str, text: str, rule: RuleClassification) -> bool:
    """Exclude replies and follow-ups from the explicit Sent import."""
    if not rule.is_job_related or _REPLY_SUBJECT_RE.match(subject or ""):
        return False
    return bool(_DIRECT_APPLICATION_SUBJECT_RE.match(subject or "")) or "hiermit bewerbe ich mich" in (text or "").casefold()


def _company_from_recipient_domain(recipients: list[str]) -> tuple[str, str] | None:
    for recipient in recipients:
        if "@" not in recipient:
            continue
        domain = recipient.rsplit("@", 1)[-1].strip().casefold()
        parts = domain.split(".")
        if len(parts) < 2 or not parts[0]:
            continue
        label = " ".join(
            part.upper() if len(part) <= 4 else part.capitalize()
            for part in re.split(r"[-_]", parts[0])
            if part
        )
        if label:
            return label, domain
    return None


def _sent_application_data(base: dict[str, Any], *, subject: str, recipients: list[str]) -> dict[str, Any]:
    """Add review-only direct-email hints when the email omits employer metadata."""
    data = dict(base)
    data["sent_kind"] = "direct_application"
    title_match = _DIRECT_APPLICATION_SUBJECT_RE.match(subject or "")
    if not data.get("position_title") and title_match:
        data["position_title"] = title_match.group("title").strip()
    if not data.get("company"):
        company = _company_from_recipient_domain(recipients)
        if company:
            data["company"], domain = company
            data["company_source"] = "recipient_domain"
            evidence = list(data.get("evidence") or [])
            evidence.append(f"Recipient domain: {domain}")
            data["evidence"] = evidence[:3]
    return data


def _safe_fallback_error(analysis: GmailAnalysis) -> str:
    reason = analysis.extracted_data.get("fallback_reason")
    if isinstance(reason, str) and reason.endswith("Error"):
        return reason
    return ""


def sync_gmail_messages_for_user(
    *,
    user: Any,
    gmail_client: Any,
    days: int = 180,
    max_results_each: int = 500,
    ai_analyzer: OpenAIEmailAnalyzer | None = None,
    reanalyze_existing: bool = False,
    include_sent: bool = False,
) -> dict[str, int]:
    """Run the bounded, per-message Gmail assistant pipeline for one user."""
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")

    candidate_days = _candidate_days(user=user, requested_days=days)
    ids = set(gmail_client.list_message_ids(build_candidate_query(candidate_days), max_results=max_results_each))
    if include_sent:
        # Sent import is a user-requested historical backfill. Unlike the
        # incremental inbox scan, it must honour the selected period exactly.
        ids.update(
            gmail_client.list_message_ids(
                build_sent_applications_query(days),
                max_results=max_results_each,
            )
        )
    existing = set(
        GmailMessage.objects.filter(user=user, message_id__in=ids)
        .exclude(processing_status=GmailProcessingStatus.FAILED)
        .values_list("message_id", flat=True)
    )
    profile_email = gmail_client.get_profile_email()
    assistant_settings = _assistant_settings(user)
    config = ai_analyzer.config if ai_analyzer else AIAnalyzerConfig.from_environment()
    analyzer = ai_analyzer or OpenAIEmailAnalyzer(config)
    policy = AIUsagePolicy.from_environment()
    initial_ai_usage = policy.daily_usage(user=user)
    ai_calls_reserved = 0
    counters = {
        "days": candidate_days,
        "fetched_candidates": len(ids),
        "candidates": len(ids),
        "created": 0,
        "skipped_existing": 0 if reanalyze_existing else len(existing),
        "failed": 0,
        "ignored_noise": 0,
        "outbound_ignored": 0,
        "outbound_imported": 0,
        "analyses_created": 0,
        "analyzed_by_rules": 0,
        "analyzed_by_ai": 0,
        "ai_limit_reached": 0,
        "ai_low_confidence": 0,
        "ai_fallbacks": 0,
        "proposals_created": 0,
        "unmatched": 0,
    }

    if reanalyze_existing:
        cached_message_ids = set(
            GmailMessage.objects.filter(
                user=user,
                received_at__gte=datetime.now(timezone.utc) - timedelta(days=days),
            ).values_list("message_id", flat=True)
        )
        message_ids = ids | cached_message_ids
    else:
        message_ids = ids - existing
        if include_sent:
            # Retry previously imported Sent messages that produced no review
            # proposal (for example, because an older analyzer missed company).
            message_ids |= set(
                GmailMessage.objects.filter(
                    user=user,
                    direction=GmailDirection.OUTBOUND,
                    received_at__gte=datetime.now(timezone.utc) - timedelta(days=days),
                    processing_status=GmailProcessingStatus.ANALYZED,
                ).values_list("message_id", flat=True)
            )
    for message_id in message_ids:
        try:
            raw = gmail_client.get_message_full(message_id)
            parsed = parse_gmail_message(raw)
            direction = determine_direction(
                from_email=parsed.from_email,
                recipient_emails=parsed.to_emails,
                profile_email=profile_email,
            )
            rule = classify_event(parsed.subject, str(raw.get("snippet") or ""), parsed.text)
            is_manual_sent_application = (
                direction == GmailDirection.OUTBOUND
                and include_sent
                and _is_direct_sent_application(subject=parsed.subject, text=parsed.text, rule=rule)
            )
            if is_manual_sent_application:
                rule = _outbound_application_rule(rule)
            message, created = _store_message(
                user=user,
                message_id=message_id,
                raw=raw,
                parsed=parsed,
                direction=direction,
                rule=rule,
            )
            counters["created"] += int(created)

            if direction == GmailDirection.OUTBOUND and not is_manual_sent_application:
                _update_message_status(message=message, status=GmailProcessingStatus.IGNORED)
                counters["outbound_ignored"] += 1
                continue
            if direction == GmailDirection.OUTBOUND:
                counters["outbound_imported"] += 1

            if rule.event_type == "noise":
                _record_analysis(
                    user=user,
                    message=message,
                    rule=rule,
                    classifier=AnalysisClassifier.RULE,
                    extracted_data=_rule_data(rule),
                )
                counters["analyses_created"] += 1
                _update_message_status(message=message, status=GmailProcessingStatus.IGNORED)
                counters["ignored_noise"] += 1
                counters["analyzed_by_rules"] += 1
                continue

            ai_enabled = bool(assistant_settings and assistant_settings.ai_enabled)
            capacity_available = initial_ai_usage + ai_calls_reserved < policy.daily_limit
            use_ai = _ai_available(ai_enabled=ai_enabled, config=config) and capacity_available

            if use_ai:
                ai_calls_reserved += 1
                try:
                    result = analyzer.analyze(
                        SanitizedEmail(
                            message_id=message_id,
                            subject=sanitize_email_text(parsed.subject),
                            from_name=parsed.from_name,
                            from_email=parsed.from_email,
                            text=sanitize_email_text(parsed.text),
                        ),
                        AIAnalysisContext(
                            rule_event_type=rule.event_type,
                            rule_confidence=rule.confidence,
                        ),
                    )
                    requires_manual_review = policy.requires_manual_review(result.confidence)
                    extracted_data = _ai_data(
                        result,
                        requires_manual_review=requires_manual_review,
                    )
                    if is_manual_sent_application:
                        extracted_data = _sent_application_data(
                            extracted_data,
                            subject=parsed.subject,
                            recipients=parsed.to_emails,
                        )
                    analysis = _record_analysis(
                        user=user,
                        message=message,
                        rule=rule,
                        classifier=AnalysisClassifier.AI,
                        extracted_data=extracted_data,
                        event_type=("application_sent" if direction == GmailDirection.OUTBOUND else result.event_type),
                        confidence=result.confidence,
                        is_job_related=(True if direction == GmailDirection.OUTBOUND else result.is_job_related),
                        model_name=config.model,
                    )
                    counters["analyses_created"] += 1
                    counters["analyzed_by_ai"] += 1
                    counters["ai_low_confidence"] += int(requires_manual_review)
                except AIAnalyzerError as error:
                    logger.warning(
                        "Gmail AI analysis failed message_id=%s error=%s",
                        message_id,
                        type(error).__name__,
                    )
                    if not policy.rules_fallback_enabled:
                        _update_message_status(
                            message=message,
                            status=GmailProcessingStatus.FAILED,
                            error=type(error).__name__,
                        )
                        counters["failed"] += 1
                        continue
                    analysis = _record_rule_fallback(
                        user=user,
                        message=message,
                        rule=rule,
                        reason=type(error).__name__,
                        extracted_data=(
                            _sent_application_data(
                                _rule_data(rule, fallback_reason=type(error).__name__),
                                subject=parsed.subject,
                                recipients=parsed.to_emails,
                            )
                            if is_manual_sent_application
                            else None
                        ),
                    )
                    counters["analyses_created"] += 1
                    counters["analyzed_by_rules"] += 1
                    counters["ai_fallbacks"] += 1
            else:
                reason = "ai_disabled"
                if _ai_available(ai_enabled=ai_enabled, config=config) and not capacity_available:
                    reason = "daily_limit_reached"
                    counters["ai_limit_reached"] += 1
                if not policy.rules_fallback_enabled:
                    _update_message_status(
                        message=message,
                        status=GmailProcessingStatus.FAILED,
                        error=reason,
                    )
                    counters["failed"] += 1
                    continue
                analysis = _record_rule_fallback(
                    user=user,
                    message=message,
                    rule=rule,
                    reason=reason,
                    extracted_data=(
                        _sent_application_data(
                            _rule_data(rule, fallback_reason=reason),
                            subject=parsed.subject,
                            recipients=parsed.to_emails,
                        )
                        if is_manual_sent_application
                        else None
                    ),
                )
                counters["analyses_created"] += 1
                counters["analyzed_by_rules"] += 1
                counters["ai_fallbacks"] += int(reason != "ai_disabled")

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
                status=(GmailProcessingStatus.PROPOSAL_CREATED if proposals else GmailProcessingStatus.ANALYZED),
                error=_safe_fallback_error(analysis),
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
        if assistant_settings:
            assistant_settings.last_successful_run_at = django_timezone.now()
            if counters["failed"]:
                assistant_settings.last_error_at = django_timezone.now()
                assistant_settings.last_error_message = "message_processing_failed"
                assistant_settings.save(
                    update_fields=[
                        "last_successful_run_at",
                        "last_error_at",
                        "last_error_message",
                        "updated_at",
                    ]
                )
            else:
                assistant_settings.last_error_at = None
                assistant_settings.last_error_message = ""
                assistant_settings.save(
                    update_fields=[
                        "last_successful_run_at",
                        "last_error_at",
                        "last_error_message",
                        "updated_at",
                    ]
                )
    return counters
