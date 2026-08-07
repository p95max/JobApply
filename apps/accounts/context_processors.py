from __future__ import annotations

from django.http import HttpRequest

from .models import UserProfile


def account_mode(request: HttpRequest) -> dict[str, bool]:
    if not request.user.is_authenticated:
        return {"is_demo_user": False}

    return {
        "is_demo_user": UserProfile.objects.filter(
            user=request.user,
            is_demo_user=True,
        ).exists()
    }
