from __future__ import annotations

from allauth.account.forms import SignupForm
from django import forms
from django.core.exceptions import ValidationError


class DisabledSignupForm(SignupForm):
    """
    Hard-disable local signup. Project uses Google OAuth only.
    """
    def clean(self):
        raise ValidationError("Sign up is disabled. Please use Google sign-in.")
