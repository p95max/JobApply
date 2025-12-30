from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class TurnstileResult:
    success: bool
    error_codes: tuple[str, ...] = ()


def verify_turnstile(response_token: str, remote_ip: str | None = None) -> TurnstileResult:
    """
    Validate Cloudflare Turnstile token using Turnstile siteverify endpoint.
    """
    if not settings.TURNSTILE_ENABLED:
        return TurnstileResult(success=True)

    if not response_token:
        return TurnstileResult(success=False, error_codes=("missing-input-response",))

    payload = {
        "secret": settings.TURNSTILE_SECRET_KEY,
        "response": response_token,
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(settings.TURNSTILE_VERIFY_URL, data=data, method="POST")

    with urllib.request.urlopen(req, timeout=5) as resp:
        raw = resp.read().decode("utf-8")

    parsed = json.loads(raw)
    success = bool(parsed.get("success"))
    error_codes = tuple(parsed.get("error-codes") or ())
    return TurnstileResult(success=success, error_codes=error_codes)
