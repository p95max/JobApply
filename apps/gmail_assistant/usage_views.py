from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse


@login_required
def token_usage(request):
    try:
        days = int(request.GET.get("days", "30"))
    except ValueError:
        days = 30
    if days not in {7, 30}:
        days = 30

    return redirect(f"{reverse('reports:ai_statistics')}?days={days}")
