from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from django.utils import timezone

from apps.gmail_assistant.models import AnalysisClassifier, GmailAnalysis

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
        return GmailAnalysis.objects.filter(
            user=user,
            classifier__in=(AnalysisClassifier.AI, AnalysisClassifier.RULE_AI),
            analyzed_at__date=timezone.localdate(),
        ).count()

    def has_capacity(self, *, user: Any, reserved: int = 0) -> bool:
        return self.daily_limit > 0 and self.daily_usage(user=user) + reserved < self.daily_limit

    def requires_manual_review(self, confidence: int) -> bool:
        return confidence < self.confidence_threshold


def sanitize_email_text(value: str) -> str:
    text = value or ""
    text = _SECRET_LINE_RE.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    text = _SECRET_SENTENCE_RE.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    return _SECRET_QUERY_RE.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
