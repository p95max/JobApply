from __future__ import annotations

import csv
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.applications.models import JobApplication
from apps.gmail_assistant.models import (
    AnalysisClassifier,
    ApplicationUpdateProposal,
    GmailAnalysis,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_stats.models import GmailMessage
from apps.reports.drive import DriveError, _validate_backup_metadata
from apps.reports.models import CloudBackupSettings
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
@override_settings(APPLICATIONS_PER_USER_LIMIT=1)
def test_import_respects_the_per_user_application_limit(user):
    JobApplication.objects.create(user=user, company="Existing GmbH", title="Developer")

    with pytest.raises(ImportValidationError, match="Application limit reached"):
        import_csv(
            user,
            _csv(
                [
                    {
                        "id": "",
                        "title": "New role",
                        "company": "New GmbH",
                        "location": "",
                        "source": "other",
                        "status": "applied",
                        "applied_at": "",
                        "recruiter_reply_at": "",
                        "notes": "",
                    }
                ]
            ),
        )

    assert JobApplication.objects.filter(user=user).count() == 1


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
        reverse("reports:toggle_auto_backup"),
    ):
        assert client.get(url).status_code == 405


@pytest.mark.django_db
def test_user_can_enable_personal_automatic_drive_backups(client, user, monkeypatch):
    import apps.reports.views as reports_views

    monkeypatch.setattr(
        reports_views,
        "get_drive_status",
        lambda _user: {"connected": True, "has_refresh_token": True},
    )
    client.force_login(user)

    response = client.post(reverse("reports:toggle_auto_backup"), {"enabled": "1"})

    assert response.status_code == 302
    assert CloudBackupSettings.objects.get(user=user).enabled is True


@pytest.mark.django_db
@override_settings(CSV_IMPORT_COOLDOWN_SECONDS=60)
def test_csv_import_returns_a_safe_error_when_rate_limited(client, user):
    from apps.reports.views import _claim_csv_import

    _claim_csv_import(user)
    client.force_login(user)
    upload = SimpleUploadedFile("applications.csv", _csv([]), content_type="text/csv")

    response = client.post(reverse("reports:import"), {"file": upload})

    assert response.status_code == 200
    assert b"Please wait" in response.content


@pytest.mark.django_db
@override_settings(DRIVE_MANUAL_OPERATION_COOLDOWN_SECONDS=60)
def test_drive_export_is_rate_limited_before_a_second_google_upload(client, user, monkeypatch):
    import apps.reports.views as reports_views

    uploads = []
    monkeypatch.setattr(reports_views, "upload_backup", lambda *args, **kwargs: uploads.append(args))
    client.force_login(user)

    first = client.post(reverse("reports:drive_export", args=["csv"]))
    second = client.post(reverse("reports:drive_export", args=["csv"]), follow=True)

    assert first.status_code == 302
    assert second.status_code == 200
    assert len(uploads) == 1
    assert b"Please wait" in second.content


@pytest.mark.django_db
def test_ai_statistics_shows_only_the_current_users_analysis_and_proposals(
    client,
    user,
    django_user_model,
):
    message = GmailMessage.objects.create(
        user=user,
        message_id="ai-stats-message",
        thread_id="ai-stats-thread",
        received_at=timezone.now(),
    )
    analysis = GmailAnalysis.objects.create(
        user=user,
        message=message,
        classifier=AnalysisClassifier.AI,
        confidence=88,
    )
    ApplicationUpdateProposal.objects.create(
        user=user,
        message=message,
        analysis=analysis,
        proposal_type=ProposalType.UPDATE_APPLICATION,
        status=ProposalStatus.PENDING,
    )
    other_user = django_user_model.objects.create_user(
        "other-report-user",
        email="other@example.com",
    )
    other_message = GmailMessage.objects.create(
        user=other_user,
        message_id="other-ai-stats-message",
        thread_id="other-ai-stats-thread",
        received_at=timezone.now(),
    )
    GmailAnalysis.objects.create(
        user=other_user,
        message=other_message,
        classifier=AnalysisClassifier.RULE,
        confidence=10,
    )

    client.force_login(user)
    response = client.get(reverse("reports:ai_statistics"))

    assert response.status_code == 200
    assert response.context["analysis_total"] == 1
    assert response.context["analysis_ai"] == 1
    assert response.context["analysis_rules"] == 0
    assert response.context["average_confidence"] == 88
    assert response.context["proposal_counts"][ProposalStatus.PENDING] == 1


@pytest.mark.django_db
def test_legacy_token_usage_url_redirects_to_ai_statistics(client, user):
    client.force_login(user)

    response = client.get(reverse("gmail_assistant:token_usage"), {"days": 7})

    assert response.status_code == 302
    assert response.url == f"{reverse('reports:ai_statistics')}?days=7"


@pytest.mark.django_db
@override_settings(TELEGRAM_OWNER_EMAIL="owner@example.com")
def test_server_backup_schedule_is_hidden_from_regular_users(client, user):
    client.force_login(user)

    response = client.get(reverse("reports:drive_backups"))

    assert response.status_code == 200
    assert b"Server backup schedule" not in response.content


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
