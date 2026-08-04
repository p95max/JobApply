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
    owner_user_id: int | None
    owner_email: str
    environment_label: str
    notifications_enabled: bool

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

        return cls(
            enabled=getenv("TELEGRAM_BOT_ENABLED", "0") == "1",
            token=getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            default_chat_id=default_chat_id,
            allowed_chat_ids=parse_id_set(getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")),
            allowed_user_ids=parse_id_set(getenv("TELEGRAM_ALLOWED_USER_IDS", "")),
            owner_user_id=owner_user_id,
            owner_email=getenv("TELEGRAM_OWNER_EMAIL", "").strip(),
            environment_label=getenv("TELEGRAM_ENV_LABEL", "DEVELOPMENT").strip() or "DEVELOPMENT",
            notifications_enabled=getenv("TELEGRAM_NOTIFICATIONS_ENABLED", "0") == "1",
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
        if missing:
            raise ValueError("Missing Telegram settings: " + ", ".join(missing))
