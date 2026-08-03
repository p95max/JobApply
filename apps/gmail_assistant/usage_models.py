from __future__ import annotations

from django.conf import settings
from django.db import models


class OpenAITokenUsage(models.Model):
    """Persistent token usage for one successful Gmail Assistant AI request."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gmail_openai_token_usage",
    )
    message = models.ForeignKey(
        "gmail_stats.GmailMessage",
        on_delete=models.CASCADE,
        related_name="openai_token_usage",
    )
    model_name = models.CharField(max_length=100)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "gmail_assistant_openaitokenusage"
        ordering = ("-created_at",)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
