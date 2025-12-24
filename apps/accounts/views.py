from __future__ import annotations

import logging

from allauth.socialaccount.providers.google.views import oauth2_login
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import redirect, render

from .models import UserProfile

logger = logging.getLogger(__name__)


def ensure_profile(user: User) -> UserProfile:
    try:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile
    except Exception:
        logger.exception("ensure_profile failed user=%s", getattr(user, "id", None))
        raise


def root(request):
    if request.user.is_authenticated:
        return redirect("/applications/")
    try:
        return oauth2_login(request)
    except Exception:
        logger.exception("root oauth2_login failed")
        return redirect("/accounts/login/")


@login_required
def consent(request):
    try:
        profile = ensure_profile(request.user)
    except Exception:
        messages.error(request, "Could not load your profile. Try again later.")
        return redirect("/")

    if request.method == "POST":
        accepted = bool(request.POST.get("consent"))
        if accepted:
            try:
                profile.accept_consent()
                messages.success(request, "Consent saved.")
                return redirect("applications:list")
            except Exception:
                logger.exception("accept_consent failed user=%s", request.user.id)
                messages.error(request, "Could not save consent. Try again.")

    return render(
        request,
        "accounts/consent.html",
        {
            "profile": profile,
            "consent_text_1": "I agree to provide access to my Google account for authentication purposes.",
            "consent_text_2": "Administration is not responsible for storing personal data beyond reasonable security measures.",
        },
    )
