from __future__ import annotations

from html import escape

from .selectors import StatusSnapshot


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
        f"Database: <b>{db_status}</b>\n"
        f"Applications: <b>{snapshot.total_applications}</b>\n"
        f"Pending Gmail proposals: <b>{snapshot.pending_proposals}</b>"
    )


def gmail_text(total: int, proposals: list) -> str:
    lines = [f"<b>Pending Gmail proposals: {total}</b>"]
    for proposal in proposals:
        application = proposal.application
        company = application.company if application else proposal.changes.get("company", "Unknown")
        title = application.title if application else proposal.changes.get("title", "Unknown")
        lines.append(
            f"\n• {escape(proposal.get_proposal_type_display())}\n"
            f"  {escape(str(company))} — {escape(str(title))}"
        )
    return "\n".join(lines)


def applications_text(summary: dict[str, int]) -> str:
    lines = [f"<b>Applications: {summary['total']}</b>"]
    for status in ("applied", "screen", "replied", "interview", "offer", "rejected", "archived"):
        lines.append(f"{escape(status.title())}: {summary.get(status, 0)}")
    return "\n".join(lines)
