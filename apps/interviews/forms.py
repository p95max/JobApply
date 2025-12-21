from __future__ import annotations

from django import forms

from apps.applications.models import ApplicationStatus, JobApplication
from .models import InterviewEvent


class InterviewEventForm(forms.ModelForm):
    class Meta:
        model = InterviewEvent
        fields = ["application", "starts_at", "ends_at", "location", "notes"]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["application"].queryset = JobApplication.objects.filter(
            user=user, status=ApplicationStatus.INTERVIEW
        )
