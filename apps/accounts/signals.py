from __future__ import annotations

from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver


@receiver(user_logged_out)
def clear_turnstile_flag_on_logout(sender, request, user, **kwargs):
    if request and hasattr(request, "session"):
        request.session.pop("turnstile_passed", None)
        request.session.modified = True
