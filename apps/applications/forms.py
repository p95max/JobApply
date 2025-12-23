from django import forms

from apps.applications.models import JobApplication


class JobApplicationForm(forms.ModelForm):
    # field limits
    TITLE_MAX = 50
    COMPANY_MAX = 50
    LOCATION_MAX = 70
    SOURCE_MAX = 50
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
        help_text=f"Max {TITLE_MAX} characters.",
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
        help_text=f"Max {COMPANY_MAX} characters.",
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
        help_text=f"Max {LOCATION_MAX} characters.",
    )
    source = forms.CharField(
        required=False,
        max_length=SOURCE_MAX,
        widget=forms.TextInput(
            attrs={
                "class": "form-control w-100",
                "maxlength": str(SOURCE_MAX),
                "data-maxlen": str(SOURCE_MAX),
                "placeholder": "LinkedIn / Indeed / Email / Referral...",
            }
        ),
        help_text=f"Max {SOURCE_MAX} characters.",
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
        help_text=f"Max {NOTES_MAX} characters.",
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
            "status": forms.Select(attrs={"class": "form-select w-100"}),
            "applied_at": forms.DateInput(
                attrs={"class": "form-control w-100", "type": "date"}
            ),
            "recruiter_reply_at": forms.DateInput(
                attrs={"class": "form-control w-100", "type": "date"}
            ),
        }

    def clean_title(self) -> str:
        value = (self.cleaned_data.get("title") or "").strip()
        if not value:
            raise forms.ValidationError("Title is required.")
        if len(value) > self.TITLE_MAX:
            raise forms.ValidationError(
                f"Title must be {self.TITLE_MAX} characters or less."
            )
        return value

    def clean_company(self) -> str:
        value = (self.cleaned_data.get("company") or "").strip()
        if not value:
            raise forms.ValidationError("Company is required.")
        if len(value) > self.COMPANY_MAX:
            raise forms.ValidationError(
                f"Company must be {self.COMPANY_MAX} characters or less."
            )
        return value

    def clean_location(self) -> str:
        value = (self.cleaned_data.get("location") or "").strip()
        if len(value) > self.LOCATION_MAX:
            raise forms.ValidationError(
                f"Location must be {self.LOCATION_MAX} characters or less."
            )
        return value

    def clean_source(self) -> str:
        value = (self.cleaned_data.get("source") or "").strip()
        if len(value) > self.SOURCE_MAX:
            raise forms.ValidationError(
                f"Source must be {self.SOURCE_MAX} characters or less."
            )
        return value

    def clean_notes(self) -> str:
        value = (self.cleaned_data.get("notes") or "").strip()
        if len(value) > self.NOTES_MAX:
            raise forms.ValidationError(
                f"Notes must be {self.NOTES_MAX} characters or less."
            )
        return value
