from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.gmail_assistant.services.token_usage import load_token_usage


@login_required
def token_usage(request):
    try:
        days = int(request.GET.get("days", "30"))
    except ValueError:
        days = 30
    if days not in {7, 30}:
        days = 30

    return render(
        request,
        "gmail_assistant/token_usage.html",
        {
            "usage": load_token_usage(days),
            "days": days,
        },
    )
