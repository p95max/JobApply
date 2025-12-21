from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone
from openpyxl import Workbook

from apps.applications.models import JobApplication


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
                a.title,
                a.company,
                a.location,
                a.source,
                a.status,
                a.applied_at.isoformat() if a.applied_at else "",
                a.recruiter_reply_at.isoformat() if a.recruiter_reply_at else "",
                a.notes,
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
                a.title,
                a.company,
                a.location,
                a.source,
                a.status,
                a.applied_at.isoformat() if a.applied_at else "",
                a.recruiter_reply_at.isoformat() if a.recruiter_reply_at else "",
                a.notes,
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
    created = 0
    updated = 0

    text = raw_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    for row in reader:
        raw_id = (row.get("id") or "").strip()
        obj = None
        if raw_id.isdigit():
            obj = JobApplication.objects.filter(user=user, id=int(raw_id)).first()

        applied_at = _parse_date(row.get("applied_at"))
        reply_at = _parse_date(row.get("recruiter_reply_at"))

        payload = {
            "title": (row.get("title") or "").strip(),
            "company": (row.get("company") or "").strip(),
            "location": (row.get("location") or "").strip(),
            "source": (row.get("source") or "").strip(),
            "status": (row.get("status") or "applied").strip(),
            "applied_at": applied_at or timezone.now().date(),
            "recruiter_reply_at": reply_at,
            "notes": row.get("notes") or "",
        }

        if obj:
            for k, v in payload.items():
                setattr(obj, k, v)
            obj.save()
            updated += 1
        else:
            JobApplication.objects.create(user=user, **payload)
            created += 1

    return {"created": created, "updated": updated}


def _parse_date(value: str | None):
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    try:
        return datetime.fromisoformat(v).date()
    except ValueError:
        return None
