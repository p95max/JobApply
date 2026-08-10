from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import transaction
from openpyxl import Workbook

from apps.applications.forms import JobApplicationForm
from apps.applications.models import JobApplication
from apps.applications.services.limits import ApplicationLimitError, ensure_application_capacity


EXPECTED_IMPORT_HEADERS = (
    "id",
    "title",
    "company",
    "location",
    "source",
    "status",
    "applied_at",
    "recruiter_reply_at",
    "notes",
)
MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 5_000
FORMULA_PREFIXES = ("=", "+", "-", "@")


class ImportValidationError(ValueError):
    """Raised when a CSV import does not satisfy the application schema."""


@dataclass(frozen=True)
class Stats:
    total: int
    by_status: dict[str, int]


def build_stats(qs) -> Stats:
    total = qs.count()
    by_status: dict[str, int] = {}
    for obj in qs.only("status"):
        by_status[obj.status] = by_status.get(obj.status, 0) + 1
    return Stats(total=total, by_status=by_status)


def export_csv(qs) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "title", "company", "location", "source", "status", "applied_at", "recruiter_reply_at", "notes"])
    for a in qs:
        w.writerow(
            [
                a.id,
                sanitize_spreadsheet_cell(a.title),
                sanitize_spreadsheet_cell(a.company),
                sanitize_spreadsheet_cell(a.location),
                sanitize_spreadsheet_cell(a.source),
                sanitize_spreadsheet_cell(a.status),
                a.applied_at.isoformat() if a.applied_at else "",
                a.recruiter_reply_at.isoformat() if a.recruiter_reply_at else "",
                sanitize_spreadsheet_cell(a.notes),
            ]
        )
    return buf.getvalue().encode("utf-8")


def export_xlsx(qs) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "applications"
    ws.append(["id", "title", "company", "location", "source", "status", "applied_at", "recruiter_reply_at", "notes"])
    for a in qs:
        ws.append(
            [
                a.id,
                sanitize_spreadsheet_cell(a.title),
                sanitize_spreadsheet_cell(a.company),
                sanitize_spreadsheet_cell(a.location),
                sanitize_spreadsheet_cell(a.source),
                sanitize_spreadsheet_cell(a.status),
                a.applied_at.isoformat() if a.applied_at else "",
                a.recruiter_reply_at.isoformat() if a.recruiter_reply_at else "",
                sanitize_spreadsheet_cell(a.notes),
            ]
        )
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def import_csv(user, raw_bytes: bytes) -> dict[str, int]:
    """
    Imports CSV with header:
    id,title,company,location,source,status,applied_at,recruiter_reply_at,notes

    Dedupe rule (per TZ): if id exists -> update; else -> create.
    """
    if len(raw_bytes) > MAX_IMPORT_BYTES:
        raise ImportValidationError(
            f"The CSV file is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB."
        )
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ImportValidationError("The CSV file must use UTF-8 encoding.") from error

    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != EXPECTED_IMPORT_HEADERS:
        headers = ",".join(reader.fieldnames or ())
        raise ImportValidationError(f"Unexpected CSV header: {headers or 'missing header'}.")

    rows = list(reader)
    if len(rows) > MAX_IMPORT_ROWS:
        raise ImportValidationError(f"A CSV import may contain at most {MAX_IMPORT_ROWS} rows.")

    owned_ids: set[int] = set()
    parsed_ids: list[int | None] = []
    for row_number, row in enumerate(rows, start=2):
        if None in row:
            raise ImportValidationError(f"Row {row_number} has more values than the header.")
        raw_id = (row.get("id") or "").strip()
        if not raw_id:
            parsed_ids.append(None)
            continue
        if not raw_id.isdigit() or int(raw_id) < 1:
            raise ImportValidationError(f"Row {row_number}: id must be a positive integer or empty.")
        parsed_id = int(raw_id)
        parsed_ids.append(parsed_id)
        owned_ids.add(parsed_id)

    created = 0
    updated = 0
    with transaction.atomic():
        # Hold the same per-user lock as every other application-creation path
        # before deciding how many rows will become new records.
        get_user_model().objects.select_for_update().get(pk=user.pk)
        existing_ids = set(
            JobApplication.objects.filter(user=user, id__in=owned_ids).values_list("id", flat=True)
        )
        create_count = sum(1 for application_id in parsed_ids if application_id not in existing_ids)
        try:
            ensure_application_capacity(user=user, create_count=create_count)
        except ApplicationLimitError as error:
            raise ImportValidationError(str(error)) from error
        for row_number, row in enumerate(rows, start=2):
            raw_id = (row.get("id") or "").strip()
            application = None
            if raw_id:
                application = JobApplication.objects.filter(user=user, id=int(raw_id)).first()
            was_existing = application is not None

            form = JobApplicationForm(
                {
                    "title": row.get("title") or "",
                    "company": row.get("company") or "",
                    "location": row.get("location") or "",
                    "source": row.get("source") or "",
                    "status": row.get("status") or "applied",
                    "applied_at": _normalise_import_date(row.get("applied_at")),
                    "recruiter_reply_at": _normalise_import_date(row.get("recruiter_reply_at")),
                    "notes": row.get("notes") or "",
                },
                instance=application,
            )
            if not form.is_valid():
                raise ImportValidationError(f"Row {row_number}: {form.errors.as_text()}")

            application = form.save(commit=False)
            application.user = user
            application.full_clean()
            application.save()
            if was_existing:
                updated += 1
            else:
                created += 1

    return {"created": created, "updated": updated}


def sanitize_spreadsheet_cell(value: object) -> str:
    """Make untrusted text safe when a CSV/XLSX is opened by spreadsheet software."""
    text = str(value or "")
    if text.lstrip(" \t\r\n").startswith(FORMULA_PREFIXES):
        return f"'{text}"
    return text


def _normalise_import_date(value: object) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    try:
        return datetime.fromisoformat(raw_value).date().isoformat()
    except ValueError:
        return raw_value
