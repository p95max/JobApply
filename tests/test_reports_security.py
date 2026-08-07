from __future__ import annotations

import csv
import io

import pytest
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.applications.models import JobApplication
from apps.reports.drive import DriveError, _validate_backup_metadata
from apps.reports.services import (
    EXPECTED_IMPORT_HEADERS,
    ImportValidationError,
    export_csv,
    export_xlsx,
    import_csv,
)


@pytest.fixture
def user(db, django_user_model):
    return django_user_model.objects.create_user(
        username="report-user",
        email="reports@example.com",
    )


def _csv(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=EXPECTED_IMPORT_HEADERS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


@pytest.mark.django_db
def test_spreadsheet_exports_neutralize_formula_cells(user):
    application = JobApplication.objects.create(
        user=user,
        title="=HYPERLINK(\"https://invalid.example\")",
        company="Example GmbH",
        notes=" @SUM(1,1)",
    )

    csv_content = export_csv(JobApplication.objects.filter(pk=application.pk)).decode()
    xlsx_content = export_xlsx(JobApplication.objects.filter(pk=application.pk))
    worksheet = load_workbook(io.BytesIO(xlsx_content)).active

    assert "'=HYPERLINK" in csv_content
    assert "' @SUM(1,1)" in csv_content
    assert worksheet["B2"].value == "'=HYPERLINK(\"https://invalid.example\")"
    assert worksheet["I2"].value == "' @SUM(1,1)"


@pytest.mark.django_db
def test_import_uses_application_form_validation_and_is_atomic(user):
    payload = _csv(
        [
            {
                "id": "",
                "title": "Valid title",
                "company": "Example GmbH",
                "location": "Berlin",
                "source": "other",
                "status": "applied",
                "applied_at": "2026-08-07T08:48:00+00:00",
                "recruiter_reply_at": "",
                "notes": "",
            },
            {
                "id": "",
                "title": "Invalid source",
                "company": "Example GmbH",
                "location": "",
                "source": "not-a-source",
                "status": "applied",
                "applied_at": "2026-08-07",
                "recruiter_reply_at": "",
                "notes": "",
            },
        ]
    )

    with pytest.raises(ImportValidationError, match="Row 3"):
        import_csv(user, payload)

    assert JobApplication.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_import_accepts_exported_datetime_values(user):
    result = import_csv(
        user,
        _csv(
            [
                {
                    "id": "",
                    "title": "Python Developer",
                    "company": "Example GmbH",
                    "location": "Berlin",
                    "source": "other",
                    "status": "applied",
                    "applied_at": "2026-08-07T08:48:00+00:00",
                    "recruiter_reply_at": "2026-08-08T08:48:00+00:00",
                    "notes": "Imported safely",
                }
            ]
        ),
    )

    application = JobApplication.objects.get(user=user)
    assert result == {"created": 1, "updated": 0}
    assert timezone.localdate(application.applied_at).isoformat() == "2026-08-07"
    assert timezone.localdate(application.recruiter_reply_at).isoformat() == "2026-08-08"


@pytest.mark.django_db
def test_drive_mutations_reject_get_requests(client, user):
    client.force_login(user)

    for url in (
        reverse("reports:drive_export", args=["csv"]),
        reverse("reports:drive_restore", args=["file-id"]),
        reverse("reports:drive_disconnect"),
    ):
        assert client.get(url).status_code == 405


def test_drive_restore_metadata_must_describe_a_small_csv_in_the_backup_folder():
    metadata = {
        "name": "manual_backup.csv",
        "mimeType": "text/csv",
        "parents": ["backups-folder"],
        "size": "1024",
    }

    _validate_backup_metadata(metadata, "backups-folder")

    with pytest.raises(DriveError, match="not in your JobApply backup folder"):
        _validate_backup_metadata({**metadata, "parents": ["another-folder"]}, "backups-folder")
    with pytest.raises(DriveError, match="Only JobApply CSV backups"):
        _validate_backup_metadata({**metadata, "mimeType": "text/plain"}, "backups-folder")
