from __future__ import annotations

from html import escape

from django.utils import timezone

from .selectors import ApplicationSummary, StatusSnapshot


def _format_dt(value) -> str:
    if value is None:
        return "not available"
    return timezone.localtime(value).strftime("%d.%m.%Y %H:%M")


def help_text(environment: str) -> str:
    return (
        f"<b>JobApply · {escape(environment)}</b>\n\n"
        "/help — available commands\n"
        "/status — service summary\n"
        "/gmail — pending Gmail proposals\n"
        "/applications — application statistics"
    )


def status_text(environment: str, snapshot: StatusSnapshot) -> str:
    db_status = "OK" if snapshot.database_ok else "FAILED"
    return (
        f"<b>JobApply · {escape(environment)}</b>\n"
        f"Commit: <code>{escape(snapshot.commit_sha)}</code>\n"
        f"Database: <b>{db_status}</b>\n"
        f"Applications: <b>{snapshot.total_applications}</b>\n"
        f"Pending Gmail proposals: <b>{snapshot.pending_proposals}</b>\n"
        f"Last Gmail sync: <b>{escape(_format_dt(snapshot.last_gmail_sync_at))}</b>\n"
        f"Next Gmail check: <b>{escape(_format_dt(snapshot.next_gmail_check_at))}</b>"
    )


def _proposal_identity(proposal) -> tuple[str, str]:
    if proposal.application:
        return proposal.application.company or "Unknown", proposal.application.title or "Unknown"

    extracted = proposal.analysis.extracted_data if proposal.analysis_id else {}
    application_changes = proposal.changes.get("application", {}) if isinstance(proposal.changes, dict) else {}
    company = extracted.get("company") or application_changes.get("company") or "Unknown"
    title = extracted.get("position_title") or application_changes.get("title") or "Unknown"
    return str(company), str(title)


def gmail_text(total: int, proposals: list) -> str:
    lines = [f"<b>Pending Gmail proposals: {total}</b>"]
    for proposal in proposals:
        company, title = _proposal_identity(proposal)
        lines.append(
            f"\n• {escape(proposal.get_proposal_type_display())}\n"
            f"  {escape(company)} — {escape(title)}"
        )
    if not proposals:
        lines.append("\nNo pending proposals.")
    return "\n".join(lines)


def applications_text(summary: ApplicationSummary) -> str:
    counts = summary.counts
    lines = [f"<b>Applications: {counts['total']}</b>"]
    for status in ("applied", "screen", "replied", "interview", "offer", "rejected", "archived"):
        lines.append(f"{escape(status.title())}: {counts.get(status, 0)}")

    if summary.next_interview:
        interview = summary.next_interview
        lines.extend(
            [
                "",
                "<b>Next interview</b>",
                f"{escape(interview.application.company)} — {escape(interview.application.title)}",
                escape(_format_dt(interview.starts_at)),
            ]
        )
    return "\n".join(lines)
