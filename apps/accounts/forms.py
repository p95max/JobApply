from __future__ import annotations

from allauth.account.forms import SignupForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class DisabledSignupForm(SignupForm):
    """
    Hard-disable local signup. Project uses Google OAuth only.
    """

    def clean(self):
        raise ValidationError(
            _("Sign up is disabled. Please use Google sign-in.")
        )