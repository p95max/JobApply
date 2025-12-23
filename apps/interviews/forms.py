from __future__ import annotations

from django import forms

from apps.applications.models import ApplicationStatus, JobApplication
from .models import InterviewEvent


class InterviewEventForm(forms.ModelForm):
    # field limits
    LOCATION_MAX = 50
    NOTES_MAX = 1000

    location = forms.CharField(
        required=False,
        max_length=LOCATION_MAX,
        widget=forms.TextInput(
            attrs={
                "class": "form-control w-100",
                "maxlength": str(LOCATION_MAX),
                "data-maxlen": str(LOCATION_MAX),
                "placeholder": "Zoom / Google Meet / Onsite address...",
            }
        ),
        help_text=f"Max {LOCATION_MAX} characters.",
    )

    notes = forms.CharField(
        required=False,
        max_length=NOTES_MAX,
        widget=forms.Textarea(
            attrs={
                "class": "form-control w-100",
                "rows": 3,
                "maxlength": str(NOTES_MAX),
                "data-maxlen": str(NOTES_MAX),
            }
        ),
        help_text=f"Max {NOTES_MAX} characters.",
    )

    class Meta:
        model = InterviewEvent
        fields = ["application", "status", "starts_at", "location", "notes"]
        widgets = {
            "application": forms.Select(attrs={"class": "form-select w-100"}),
            "status": forms.Select(attrs={"class": "form-select w-100"}),
            "starts_at": forms.DateTimeInput(
                attrs={"class": "form-control w-100", "type": "datetime-local"}
            ),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["application"].queryset = JobApplication.objects.filter(
            user=user, status=ApplicationStatus.INTERVIEW
        )

    def clean_location(self) -> str:
        value = (self.cleaned_data.get("location") or "").strip()
        if len(value) > self.LOCATION_MAX:
            raise forms.ValidationError(
                f"Location must be {self.LOCATION_MAX} characters or less."
            )
        return value

    def clean_notes(self) -> str:
        value = (self.cleaned_data.get("notes") or "").strip()
        if len(value) > self.NOTES_MAX:
            raise forms.ValidationError(
                f"Notes must be {self.NOTES_MAX} characters or less."
            )
        return value
