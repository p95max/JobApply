from __future__ import annotations

import logging
import re

from django.db import DatabaseError

_USAGE_LINE = re.compile(
    r"OpenAI Gmail analysis completed message_id=(?P<message_id>\S+) "
    r"model=(?P<model>\S+) .*?input_tokens=(?P<input>\d+) "
    r"output_tokens=(?P<output>\d+)"
)


class PostgreSQLTokenUsageHandler(logging.Handler):
    """Persist successful Gmail Assistant OpenAI usage without relying on journald.

    Usage accounting is telemetry and must never turn a successful model response
    into a failed Gmail analysis. This also keeps the isolated analyzer unit tests
    independent from Django database access.
    """

    def emit(self, record: logging.LogRecord) -> None:
        match = _USAGE_LINE.search(record.getMessage())
        if not match:
            return

        try:
            from apps.gmail_assistant.usage_models import OpenAITokenUsage
            from apps.gmail_stats.models import GmailMessage

            messages = GmailMessage.objects.filter(
                message_id=match.group("message_id")
            ).select_related("user")
            for message in messages:
                OpenAITokenUsage.objects.create(
                    user=message.user,
                    message=message,
                    model_name=match.group("model"),
                    input_tokens=int(match.group("input")),
                    output_tokens=int(match.group("output")),
                )
        except (DatabaseError, LookupError, RuntimeError, ValueError):
            # Django raises RuntimeError when a unit test intentionally forbids
            # database access. Usage persistence must stay best-effort.
            self.handleError(record)
