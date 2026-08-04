import logging

from django.apps import AppConfig


class GmailAssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.gmail_assistant"
    verbose_name = "Gmail Assistant"

    def ready(self) -> None:
        # Register models and signal handlers kept in separate modules.
        from apps.gmail_assistant import signals, usage_models  # noqa: F401
        from apps.gmail_assistant.services.token_usage_handler import (
            PostgreSQLTokenUsageHandler,
        )

        logger = logging.getLogger("apps.gmail_assistant.services.ai_analyzer")
        if not any(isinstance(handler, PostgreSQLTokenUsageHandler) for handler in logger.handlers):
            logger.addHandler(PostgreSQLTokenUsageHandler(level=logging.INFO))
        logger.setLevel(logging.INFO)
