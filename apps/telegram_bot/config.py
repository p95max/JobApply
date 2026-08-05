from __future__ import annotations

from dataclasses import dataclass
from os import getenv


def parse_id_set(raw: str) -> frozenset[int]:
    values: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            values.add(int(item))
        except ValueError as exc:
            raise ValueError(f"Invalid Telegram ID: {item!r}") from exc
    return frozenset(values)


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool
    token: str
    default_chat_id: int | None
    allowed_chat_ids: frozenset[int]
    allowed_user_ids: frozenset[int]
    owner_email: str
    environment_label: str
    notifications_enabled: bool
    owner_user_id: int | None = None
    callback_ttl_seconds: int = 900
    rate_limit_count: int = 20
    rate_limit_window_seconds: int = 60
    deploy_enabled: bool = False
    deploy_confirmation_ttl_seconds: int = 300
    production_branch: str = "agent/vps-no-docker-deploy"

    @classmethod
    def from_env(cls) -> "TelegramConfig":
        default_chat = getenv("TELEGRAM_DEFAULT_CHAT_ID", "").strip()
        owner_user = getenv("TELEGRAM_OWNER_USER_ID", "").strip()
        try:
            default_chat_id = int(default_chat) if default_chat else None
        except ValueError as exc:
            raise ValueError("TELEGRAM_DEFAULT_CHAT_ID must be an integer") from exc
        try:
            owner_user_id = int(owner_user) if owner_user else None
        except ValueError as exc:
            raise ValueError("TELEGRAM_OWNER_USER_ID must be an integer") from exc

        callback_ttl_seconds = _positive_int("TELEGRAM_CALLBACK_TTL_SECONDS", 900)
        rate_limit_count = _non_negative_int("TELEGRAM_RATE_LIMIT_COUNT", 20)
        rate_limit_window_seconds = _positive_int("TELEGRAM_RATE_LIMIT_WINDOW_SECONDS", 60)
        deploy_confirmation_ttl_seconds = _positive_int("TELEGRAM_DEPLOY_CONFIRMATION_TTL_SECONDS", 300)
        production_branch = getenv("JOBAPPLY_PRODUCTION_BRANCH", "agent/vps-no-docker-deploy").strip()
        if not production_branch or any(char.isspace() for char in production_branch):
            raise ValueError("JOBAPPLY_PRODUCTION_BRANCH must be a branch name")

        return cls(
            enabled=getenv("TELEGRAM_BOT_ENABLED", "0") == "1",
            token=getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            default_chat_id=default_chat_id,
            allowed_chat_ids=parse_id_set(getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")),
            allowed_user_ids=parse_id_set(getenv("TELEGRAM_ALLOWED_USER_IDS", "")),
            owner_email=getenv("TELEGRAM_OWNER_EMAIL", "").strip(),
            environment_label=getenv("TELEGRAM_ENV_LABEL", "DEVELOPMENT").strip() or "DEVELOPMENT",
            notifications_enabled=getenv("TELEGRAM_NOTIFICATIONS_ENABLED", "0") == "1",
            owner_user_id=owner_user_id,
            callback_ttl_seconds=callback_ttl_seconds,
            rate_limit_count=rate_limit_count,
            rate_limit_window_seconds=rate_limit_window_seconds,
            deploy_enabled=getenv("TELEGRAM_DEPLOY_ENABLED", "0") == "1",
            deploy_confirmation_ttl_seconds=deploy_confirmation_ttl_seconds,
            production_branch=production_branch,
        )

    def validate_for_polling(self) -> None:
        if not self.enabled:
            return
        missing = []
        if not self.token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.allowed_chat_ids:
            missing.append("TELEGRAM_ALLOWED_CHAT_IDS")
        if not self.allowed_user_ids:
            missing.append("TELEGRAM_ALLOWED_USER_IDS")
        if not self.owner_email:
            missing.append("TELEGRAM_OWNER_EMAIL")
        if self.deploy_enabled and self.owner_user_id is None:
            missing.append("TELEGRAM_OWNER_USER_ID")
        if missing:
            raise ValueError("Missing Telegram settings: " + ", ".join(missing))


def _positive_int(name: str, default: int) -> int:
    value = _non_negative_int(name, default)
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _non_negative_int(name: str, default: int) -> int:
    raw = getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value
