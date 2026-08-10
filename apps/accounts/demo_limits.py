from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.crypto import salted_hmac


class DemoStartRateLimitError(RuntimeError):
    def __init__(self, *, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Demo start is temporarily rate limited")


def client_ip(request) -> str:
    """Use a proxy header only when the deployment explicitly trusts it."""
    if getattr(settings, "DEMO_START_TRUST_X_FORWARDED_FOR", False):
        forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR", "")).split(",")[0].strip()
        if forwarded:
            return forwarded
    return str(request.META.get("REMOTE_ADDR", "unknown"))


def claim_demo_start(*, ip_address: str) -> None:
    """Reserve a short-lived, privacy-preserving anonymous demo-start allowance."""
    identifier = salted_hmac("jobapply-demo-start", ip_address).hexdigest()
    daily_key = f"demo-start:daily:{timezone.localdate().isoformat()}:{identifier}"
    cooldown_key = f"demo-start:cooldown:{identifier}"
    cooldown_seconds = settings.DEMO_START_COOLDOWN_SECONDS

    if cooldown_seconds and not cache.add(cooldown_key, "1", timeout=cooldown_seconds):
        raise DemoStartRateLimitError(retry_after_seconds=cooldown_seconds)

    if cache.add(daily_key, 1, timeout=24 * 60 * 60):
        return

    try:
        count = cache.incr(daily_key)
    except ValueError:
        # An evicted key is safe to treat as a fresh allowance.
        cache.set(daily_key, 1, timeout=24 * 60 * 60)
        return
    if count > settings.DEMO_START_MAX_PER_IP_PER_DAY:
        raise DemoStartRateLimitError(retry_after_seconds=24 * 60 * 60)
