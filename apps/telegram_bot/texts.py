from __future__ import annotations

from html import escape

from django.utils import timezone

from .diagnostics import DoctorSnapshot, HealthSnapshot
from .proposal_actions import ACCEPT_ACTION, REJECT_ACTION, callback_data
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
        "/applications — application statistics\n"
        "/health — runtime health checks\n"
        "/doctor — diagnostics (owner only)\n"
        "/deploy — queue production deploy (owner only)"
    )


def status_text(environment: str, snapshot: StatusSnapshot) -> str:
    db_status = "OK" if snapshot.database_ok else "FAILED"
    commit_line = f"Commit: <code>{escape(snapshot.commit_sha)}</code>"
    if snapshot.commit_at is not None:
        commit_line += f" · {escape(_format_dt(snapshot.commit_at))}"

    lines = [
        f"<b>JobApply · {escape(environment)}</b>",
        commit_line,
        f"Database: <b>{db_status}</b>",
        f"Applications: <b>{snapshot.total_applications}</b>",
        f"Pending Gmail proposals: <b>{snapshot.pending_proposals}</b>",
        f"Last Gmail sync: <b>{escape(_format_dt(snapshot.last_gmail_sync_at))}</b>",
        f"Next Gmail check: <b>{escape(_format_dt(snapshot.next_gmail_check_at))}</b>",
    ]
    if snapshot.worker_heartbeats:
        lines.extend(["", "<b>Workers</b>"])
        labels = {"gmail_worker": "Gmail worker", "telegram_bot": "Telegram Bot", "backup_worker": "Backup worker"}
        for heartbeat in snapshot.worker_heartbeats:
            state = "STALE" if heartbeat.is_stale else "OK"
            lines.append(
                f"{escape(labels.get(heartbeat.worker_name, heartbeat.worker_name))}: "
                f"<b>{state}</b> · {escape(_format_dt(heartbeat.last_seen_at))}"
            )
    return "\n".join(lines)


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


def gmail_keyboard(proposals: list, *, detail_url) -> dict[str, list[list[dict[str, str]]]] | None:
    rows: list[list[dict[str, str]]] = []
    for proposal in proposals:
        rows.append(
            [
                {"text": "Open", "url": detail_url(proposal.pk)},
                {"text": "Accept", "callback_data": callback_data(proposal.pk, ACCEPT_ACTION)},
                {"text": "Reject", "callback_data": callback_data(proposal.pk, REJECT_ACTION)},
            ]
        )
    return {"inline_keyboard": rows} if rows else None


def health_text(environment: str, snapshot: HealthSnapshot) -> str:
    database = "OK" if snapshot.database_ok else "FAILED"
    lines = [
        f"<b>Health · {escape(environment)}</b>",
        f"Database: <b>{database}</b>",
        f"Free disk: <b>{snapshot.free_disk_mb} MB</b>",
        "",
        "<b>Workers</b>",
    ]
    for heartbeat in snapshot.worker_heartbeats:
        state = "STALE" if heartbeat.is_stale else "OK"
        lines.append(f"{escape(heartbeat.worker_name)}: <b>{state}</b>")
    return "\n".join(lines)


def doctor_text(environment: str, snapshot: DoctorSnapshot) -> str:
    migration_status = "unknown" if snapshot.pending_migrations < 0 else str(snapshot.pending_migrations)
    lines = [
        f"<b>Doctor · {escape(environment)}</b>",
        f"Branch: <code>{escape(snapshot.branch)}</code>",
        f"Working tree: <b>{'DIRTY' if snapshot.is_dirty else 'clean'}</b>",
        f"Pending migrations: <b>{migration_status}</b>",
        "",
        "<b>Systemd units</b>",
    ]
    lines.extend(f"{escape(unit)}: <b>{escape(state)}</b>" for unit, state in snapshot.unit_states)
    if snapshot.worker_errors:
        lines.extend(["", "<b>Recent worker errors</b>"])
        lines.extend(escape(error) for error in snapshot.worker_errors)
    return "\n".join(lines)
