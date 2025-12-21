from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import redirect, render

from .models import UserProfile


def ensure_profile(user: User) -> UserProfile:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile

def landing(request):
    if request.user.is_authenticated:
        return redirect("applications:list")
    return render(request, "landing.html")

@login_required
def home(request):
    return redirect("applications:list")


@login_required
def consent(request):
    profile = ensure_profile(request.user)

    if request.method == "POST":
        accepted = request.POST.get("consent") == "on"
        if accepted:
            profile.accept_consent()
            return redirect("applications:list")

    return render(
        request,
        "accounts/consent.html",
        {
            "profile": profile,
            "consent_text_1": "I agree to provide access to my Google account for authentication purposes.",
            "consent_text_2": "Administration is not responsible for storing personal data beyond reasonable security measures.",
        },
    )
