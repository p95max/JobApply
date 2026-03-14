from datetime import datetime, time

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.applications.models import JobApplication


class JobApplicationForm(forms.ModelForm):
    TITLE_MAX = 50
    COMPANY_MAX = 50
    LOCATION_MAX = 70
    NOTES_MAX = 1000

    title = forms.CharField(
        max_length=TITLE_MAX,
        widget=forms.TextInput(
            attrs={
                "class": "form-control w-100",
                "maxlength": str(TITLE_MAX),
                "data-maxlen": str(TITLE_MAX),
            }
        ),
        help_text=_("Max %(max)s characters.") % {"max": TITLE_MAX},
    )

    company = forms.CharField(
        max_length=COMPANY_MAX,
        widget=forms.TextInput(
            attrs={
                "class": "form-control w-100",
                "maxlength": str(COMPANY_MAX),
                "data-maxlen": str(COMPANY_MAX),
            }
        ),
        help_text=_("Max %(max)s characters.") % {"max": COMPANY_MAX},
    )

    location = forms.CharField(
        required=False,
        max_length=LOCATION_MAX,
        widget=forms.TextInput(
            attrs={
                "class": "form-control w-100",
                "maxlength": str(LOCATION_MAX),
                "data-maxlen": str(LOCATION_MAX),
            }
        ),
        help_text=_("Max %(max)s characters.") % {"max": LOCATION_MAX},
    )

    applied_at = forms.DateField(
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(
            attrs={"class": "form-control w-100", "type": "date"}
        ),
    )

    recruiter_reply_at = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(
            attrs={"class": "form-control w-100", "type": "date"}
        ),
    )

    notes = forms.CharField(
        required=False,
        max_length=NOTES_MAX,
        widget=forms.Textarea(
            attrs={
                "class": "form-control w-100",
                "rows": 4,
                "maxlength": str(NOTES_MAX),
                "data-maxlen": str(NOTES_MAX),
            }
        ),
        help_text=_("Max %(max)s characters.") % {"max": NOTES_MAX},
    )

    class Meta:
        model = JobApplication
        fields = [
            "title",
            "company",
            "location",
            "source",
            "status",
            "applied_at",
            "recruiter_reply_at",
            "notes",
        ]
        widgets = {
            "source": forms.Select(attrs={"class": "form-select w-100"}),
            "status": forms.Select(attrs={"class": "form-select w-100"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source"].required = False
        self.fields["source"].choices = [("", _("Select source"))] + list(
            self.fields["source"].choices
        )

    def _date_to_aware_datetime(self, value):
        if not value:
            return None

        naive_dt = datetime.combine(value, time.min)
        return timezone.make_aware(naive_dt, timezone.get_default_timezone())

    def clean_title(self) -> str:
        value = (self.cleaned_data.get("title") or "").strip()
        if not value:
            raise forms.ValidationError(_("Title is required."))
        if len(value) > self.TITLE_MAX:
            raise forms.ValidationError(
                _("Title must be %(max)s characters or less.") % {"max": self.TITLE_MAX}
            )
        return value

    def clean_company(self) -> str:
        value = (self.cleaned_data.get("company") or "").strip()
        if not value:
            raise forms.ValidationError(_("Company is required."))
        if len(value) > self.COMPANY_MAX:
            raise forms.ValidationError(
                _("Company must be %(max)s characters or less.") % {"max": self.COMPANY_MAX}
            )
        return value

    def clean_location(self) -> str:
        value = (self.cleaned_data.get("location") or "").strip()
        if len(value) > self.LOCATION_MAX:
            raise forms.ValidationError(
                _("Location must be %(max)s characters or less.") % {"max": self.LOCATION_MAX}
            )
        return value

    def clean_applied_at(self):
        value = self.cleaned_data.get("applied_at")
        if not value:
            raise forms.ValidationError(_("Applied date is required."))
        return self._date_to_aware_datetime(value)

    def clean_recruiter_reply_at(self):
        value = self.cleaned_data.get("recruiter_reply_at")
        return self._date_to_aware_datetime(value)

    def clean_notes(self) -> str:
        value = (self.cleaned_data.get("notes") or "").strip()
        if len(value) > self.NOTES_MAX:
            raise forms.ValidationError(
                _("Notes must be %(max)s characters or less.") % {"max": self.NOTES_MAX}
            )
        return value
