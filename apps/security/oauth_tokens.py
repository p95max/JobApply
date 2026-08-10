from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


_PREFIX = "enc:v1:"


class OAuthTokenError(RuntimeError):
    """An OAuth credential could not be safely decrypted."""


def encrypt_oauth_token(value: str | None) -> str:
    if not value or value.startswith(_PREFIX):
        return value or ""
    encrypted = _fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return f"{_PREFIX}{encrypted}"


def decrypt_oauth_token(value: str | None) -> str:
    if not value:
        return ""
    if not value.startswith(_PREFIX):
        # Read legacy values during the migration rollout. They are encrypted
        # when saved next, and the data migration handles existing records.
        return value
    try:
        return _fernet().decrypt(value[len(_PREFIX) :].encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as error:
        raise OAuthTokenError("OAuth credential cannot be decrypted") from error


def _fernet() -> Fernet:
    # A dedicated stable key allows later rotation. Falling back to Django's
    # already-required secret keeps current deployments functional until it is set.
    material = str(getattr(settings, "OAUTH_TOKEN_ENCRYPTION_KEY", "") or settings.SECRET_KEY)
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))
