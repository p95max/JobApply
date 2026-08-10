from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

_DEFAULT_DAILY_LIMIT = 50
_DEFAULT_CONFIDENCE_THRESHOLD = 80
_SECRET_LINE_RE = re.compile(
    r"(?im)^(?P<prefix>\s*(?:password|passwort|kennwort|token|api[ _-]?key|access[ _-]?code|login|username|benutzername)\s*(?:lautet)?\s*[:=]\s*)(?P<value>.+)$"
)
_SECRET_SENTENCE_RE = re.compile(
    r"(?i)(?P<prefix>\b(?:password|passwort|kennwort|token|api[ _-]?key|access[ _-]?code|username|benutzername)\s+(?:is|ist|lautet)\s*[:=]?\s*)(?P<value>\S+)"
)
_SECRET_QUERY_RE = re.compile(
    r"(?i)(?P<prefix>[?&](?:token|key|api_key|apikey|password|passwort|code)=)(?P<value>[^&#\s]+)"
)


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


@dataclass(frozen=True)
class AIUsagePolicy:
    daily_limit: int
    confidence_threshold: int
    rules_fallback_enabled: bool

    @classmethod
    def from_environment(cls) -> "AIUsagePolicy":
        return cls(
            daily_limit=_bounded_int("GMAIL_ASSISTANT_AI_DAILY_LIMIT", _DEFAULT_DAILY_LIMIT, 0, 10000),
            confidence_threshold=_bounded_int(
                "GMAIL_ASSISTANT_AI_CONFIDENCE_THRESHOLD",
                _DEFAULT_CONFIDENCE_THRESHOLD,
                0,
                100,
            ),
            rules_fallback_enabled=os.getenv("GMAIL_ASSISTANT_RULES_FALLBACK_ENABLED", "1") == "1",
        )

    def daily_usage(self, *, user: Any) -> int:
        # Keep ORM imports local so pure policy/sanitization unit tests do not
        # require Django initialization or pytest-django.
        from django.utils import timezone

        from apps.gmail_assistant.models import GmailAssistantSettings

        today = timezone.localdate()
        settings_obj = GmailAssistantSettings.objects.filter(user=user).only(
            "ai_daily_usage_date", "ai_daily_usage_count", "ai_daily_usage_reset_at"
        ).first()
        if settings_obj and settings_obj.ai_daily_usage_date == today:
            return settings_obj.ai_daily_usage_count
        return self._legacy_daily_usage(user=user, today=today, settings_obj=settings_obj)

    def reserve_call(self, *, user: Any) -> bool:
        """Atomically reserve one potentially billable AI call for this user."""
        from django.contrib.auth import get_user_model
        from django.db import transaction
        from django.utils import timezone

        from apps.gmail_assistant.models import GmailAssistantSettings

        if self.daily_limit <= 0:
            return False
        today = timezone.localdate()
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=user.pk)
            settings_obj, _ = GmailAssistantSettings.objects.get_or_create(user=user)
            settings_obj = GmailAssistantSettings.objects.select_for_update().get(pk=settings_obj.pk)
            if settings_obj.ai_daily_usage_date != today:
                settings_obj.ai_daily_usage_date = today
                settings_obj.ai_daily_usage_count = self._legacy_daily_usage(
                    user=user,
                    today=today,
                    settings_obj=settings_obj,
                )
            if settings_obj.ai_daily_usage_count >= self.daily_limit:
                if settings_obj.pk:
                    settings_obj.save(update_fields=["ai_daily_usage_date", "ai_daily_usage_count", "updated_at"])
                return False
            settings_obj.ai_daily_usage_count += 1
            settings_obj.save(update_fields=["ai_daily_usage_date", "ai_daily_usage_count", "updated_at"])
        return True

    @staticmethod
    def _legacy_daily_usage(*, user: Any, today: date, settings_obj: Any | None) -> int:
        from apps.gmail_assistant.models import AnalysisClassifier, GmailAnalysis

        queryset = GmailAnalysis.objects.filter(
            user=user,
            classifier__in=(AnalysisClassifier.AI, AnalysisClassifier.RULE_AI),
            analyzed_at__date=today,
        )
        reset_at = getattr(settings_obj, "ai_daily_usage_reset_at", None)
        if reset_at is not None:
            queryset = queryset.filter(analyzed_at__gte=reset_at)
        return queryset.count()

    def has_capacity(self, *, user: Any, reserved: int = 0) -> bool:
        return self.daily_limit > 0 and self.daily_usage(user=user) + reserved < self.daily_limit

    def requires_manual_review(self, confidence: int) -> bool:
        return confidence < self.confidence_threshold


def sanitize_email_text(value: str) -> str:
    text = value or ""
    text = _SECRET_LINE_RE.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    text = _SECRET_SENTENCE_RE.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    return _SECRET_QUERY_RE.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
