from __future__ import annotations

from html import escape

from django.utils import timezone

from .diagnostics import DoctorSnapshot, HealthSnapshot
from .deployments import deploy_callback_data
from .selectors import ApplicationSummary, StatusSnapshot


def _format_dt(value) -> str:
    if value is None:
        return "not available"
    return timezone.localtime(value).strftime("%d.%m.%Y %H:%M")


def _state_icon(ok: bool) -> str:
    return "✅" if ok else "❌"


def help_text(environment: str, *, is_admin: bool) -> str:
    lines = [
        f"🤖 <b>JobApply{' · ' + escape(environment) if is_admin else ''}</b>",
        "",
        "<b>Available commands</b>",
        "ℹ️ /help — available commands",
        "🟢 /ping — check whether the bot is online",
        "📨 /gmail — pending Gmail proposals",
        "📋 /applications — application statistics",
    ]
    if is_admin:
        lines.extend(["", "🛠 /admin — administrator commands"])
    return "\n".join(lines)


def admin_text() -> str:
    return (
        "🛠 <b>Administrator commands</b>\n\n"
        "📊 /status — service summary\n"
        "👥 /newusers — users registered in the last 7 days\n"
        "🩺 /health — runtime health checks\n"
        "🛠 /doctor — extended diagnostics\n"
        "🚀 /deploy — queue production deploy"
    )


def new_users_text(summary, *, days: int = 7) -> str:
    users, demo_count = summary
    lines = [f"👥 <b>New users · last {days} days</b>", ""]
    lines.append(f"Registered users: <b>{len(users)}</b>")
    lines.append(f"🧪 Demo workspaces: <b>{demo_count}</b>")

    if users:
        lines.append("")
        for user in users:
            email = escape((user.email or "no email").strip())
            lines.append(f"• <code>{email}</code> · {escape(_format_dt(user.date_joined))}")
    return "\n".join(lines)


def status_text(environment: str, snapshot: StatusSnapshot) -> str:
    commit_at = _format_dt(snapshot.commit_at)
    commit_line = f"🔖 Commit: <code>{escape(snapshot.commit_sha)}</code> · {escape(commit_at)}"

    lines = [
        f"📊 <b>JobApply status · {escape(environment)}</b>",
        "",
        commit_line,
        f"{_state_icon(snapshot.database_ok)} Database: <b>{'OK' if snapshot.database_ok else 'FAILED'}</b>",
        f"👥 Active user accounts: <b>{snapshot.active_user_count}</b>",
        f"🕒 Last Gmail sync: <b>{escape(_format_dt(snapshot.last_gmail_sync_at))}</b>",
        f"⏭ Next Gmail check: <b>{escape(_format_dt(snapshot.next_gmail_check_at))}</b>",
    ]
    if snapshot.worker_heartbeats:
        lines.extend(["", "⚙️ <b>Workers</b>"])
        labels = {"gmail_worker": "Gmail worker", "telegram_bot": "Telegram bot", "backup_worker": "Backup worker"}
        for heartbeat in snapshot.worker_heartbeats:
            state = "STALE" if heartbeat.is_stale else "OK"
            icon = "⚠️" if heartbeat.is_stale else "✅"
            lines.append(
                f"{icon} {escape(labels.get(heartbeat.worker_name, heartbeat.worker_name))}: "
                f"<b>{state}</b> · {escape(_format_dt(heartbeat.last_seen_at))}"
            )
    return "\n".join(lines)


def gmail_text(total: int, *, assistant_url: str = "") -> str:
    if not total:
        return "📨 <b>Gmail Assistant</b>\n\n✅ No pending proposals."
    return (
        "📨 <b>Gmail Assistant</b>\n\n"
        f"Pending proposals: <b>{total}</b>\n"
        "Review the source emails and proposed changes in JobApply."
    )


def applications_text(summary: ApplicationSummary, *, applications_url: str = "") -> str:
    counts = summary.counts
    labels = (
        ("applied", "📤 Applied"),
        ("screen", "🔎 Screening"),
        ("replied", "💬 Replied"),
        ("interview", "📅 Interview"),
        ("offer", "🎉 Offer"),
        ("rejected", "❌ Rejected"),
        ("archived", "🗄 Archived"),
    )
    lines = [f"📋 <b>Applications: {counts['total']}</b>", ""]
    for status, label in labels:
        lines.append(f"{label}: <b>{counts.get(status, 0)}</b>")

    if summary.next_interview:
        interview = summary.next_interview
        lines.extend(
            [
                "",
                "📅 <b>Next interview</b>",
                f"🏢 {escape(interview.application.company)}",
                f"💼 {escape(interview.application.title)}",
                f"🕒 {escape(_format_dt(interview.starts_at))}",
            ]
        )
    return "\n".join(lines)


def deploy_keyboard(request_id: int) -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [
                {"text": "🚀 Confirm deploy", "callback_data": deploy_callback_data(request_id, "confirm")},
                {"text": "✖️ Cancel", "callback_data": deploy_callback_data(request_id, "cancel")},
            ]
        ]
    }


def health_text(environment: str, snapshot: HealthSnapshot) -> str:
    lines = [
        f"🩺 <b>Health · {escape(environment)}</b>",
        "",
        f"{_state_icon(snapshot.database_ok)} Database: <b>{'OK' if snapshot.database_ok else 'FAILED'}</b>",
        f"💾 Free disk: <b>{snapshot.free_disk_mb} MB</b>",
        "",
        "⚙️ <b>Workers</b>",
    ]
    for heartbeat in snapshot.worker_heartbeats:
        state = "STALE" if heartbeat.is_stale else "OK"
        icon = "⚠️" if heartbeat.is_stale else "✅"
        lines.append(f"{icon} {escape(heartbeat.worker_name)}: <b>{state}</b>")
    return "\n".join(lines)


def doctor_text(environment: str, snapshot: DoctorSnapshot) -> str:
    migration_status = "unknown" if snapshot.pending_migrations < 0 else str(snapshot.pending_migrations)
    unit_icons = {"active": "🟢", "failed": "🔴", "inactive": "⚪"}
    unavailable_units = tuple(
        unit
        for unit, state in snapshot.unit_states
        if state != "active" and not (unit == "jobapply-backup.service" and state == "inactive")
    )
    backup_heartbeat = next(
        (item for item in snapshot.health.worker_heartbeats if item.worker_name == "backup_worker"),
        None,
    )
    has_failed_unit = bool(unavailable_units)
    has_failed_backup = bool(backup_heartbeat and backup_heartbeat.last_error_message)
    has_stale_worker = any(worker.is_stale for worker in snapshot.health.worker_heartbeats)
    has_critical_issue = (
        not snapshot.health.database_ok or snapshot.pending_migrations > 0 or has_failed_unit or has_failed_backup
    )
    has_warning = (
        snapshot.is_dirty or snapshot.pending_migrations < 0 or has_stale_worker or bool(snapshot.worker_errors)
    )
    if has_critical_issue:
        overall_icon, overall_label = "🔴", "ACTION REQUIRED"
    elif has_warning:
        overall_icon, overall_label = "🟡", "ATTENTION NEEDED"
    else:
        overall_icon, overall_label = "🟢", "HEALTHY"
    lines = [
        f"🛠 <b>Doctor · {escape(environment)}</b>",
        "",
        f"🌿 Branch: <code>{escape(snapshot.branch)}</code>",
        f"{'⚠️' if snapshot.is_dirty else '✅'} Working tree: <b>{'DIRTY' if snapshot.is_dirty else 'clean'}</b>",
        f"🗃 Pending migrations: <b>{migration_status}</b>",
        "",
        "⚙️ <b>Systemd units</b>",
    ]
    for unit, state in snapshot.unit_states:
        if unit == "jobapply-backup.service":
            if state == "failed" or (backup_heartbeat and backup_heartbeat.last_error_message):
                icon, label = "🔴", "last backup failed"
            elif backup_heartbeat and backup_heartbeat.last_success_at:
                icon = "⚠️" if backup_heartbeat.is_stale else "✅"
                label = f"last backup successful · {_format_dt(backup_heartbeat.last_success_at)}"
            else:
                icon, label = "⚪", "last backup not recorded"
            lines.append(f"{icon} {escape(unit)}: <b>{escape(label)}</b>")
            continue
        label = state
        lines.append(f"{unit_icons.get(state, '⚠️')} {escape(unit)}: <b>{escape(label)}</b>")
    if snapshot.worker_errors:
        lines.extend(["", "⚠️ <b>Recent worker errors</b>"])
        lines.extend(f"<pre><code>{escape(error)}</code></pre>" for error in snapshot.worker_errors)
    if unavailable_units:
        lines.extend(["", "🛠 <b>Check on server</b>"])
        lines.extend(
            f"<code>journalctl -u {escape(unit)} -n 100 --no-pager</code>"
            for unit in unavailable_units
        )
    lines.extend(["", f"{overall_icon} <b>Overall: {overall_label}</b>"])
    return "\n".join(lines)
