from __future__ import annotations

from django import forms

from .models import JobApplication


class JobApplicationForm(forms.ModelForm):
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
            "applied_at": forms.DateInput(attrs={"type": "date"}),
            "recruiter_reply_at": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }
