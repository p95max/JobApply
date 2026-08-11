from __future__ import annotations

import os
import subprocess
from html import escape
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import TelegramDeployRequest, TelegramDeployRequestStatus


DEPLOY_SERVICE = "jobapply-deploy.service"
DEPLOY_REQUEST_MARKER = Path(os.getenv("JOBAPPLY_DEPLOY_REQUEST_MARKER", "/run/jobapply/deploy.requested"))
QUEUE_STATUS_FILE = Path("/var/tmp/jobapply-background-job.status")


@dataclass(frozen=True)
class DeployPreparation:
    request: TelegramDeployRequest | None
    message: str
    outcome: str


@dataclass(frozen=True)
class DeployActionResult:
    request: TelegramDeployRequest | None
    message: str
    outcome: str


def deploy_callback_data(request_id: int, action: str) -> str:
    if action not in {"confirm", "cancel"}:
        raise ValueError("Unsupported deploy action")
    return f"deploy:{request_id}:{action}"


def parse_deploy_callback(value: object) -> tuple[int, str] | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) != 3 or parts[0] != "deploy" or parts[2] not in {"confirm", "cancel"}:
        return None
    try:
        request_id = int(parts[1])
    except ValueError:
        return None
    return (request_id, parts[2]) if request_id > 0 else None


def prepare_deploy_request(
    *,
    telegram_user_id: int,
    chat_id: int,
    branch: str,
    ttl_seconds: int,
) -> DeployPreparation:
    if (busy := current_queue_status()) is not None:
        return DeployPreparation(None, f"A background job is busy: {busy}", "busy")
    current_commit, target_commit = _deploy_commits(branch)
    if current_commit is None or target_commit is None:
        return DeployPreparation(None, "Could not read deploy commits. Check JobApply logs.", "failed")
    current_commit_date = _commit_date("HEAD")
    target_commit_date = _commit_date(target_commit)
    target_description = _target_commit_description(branch=branch, revision=target_commit)
    request = TelegramDeployRequest.objects.create(
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        current_commit=current_commit,
        target_commit=target_commit,
        target_description=target_description,
        expires_at=timezone.now() + timedelta(seconds=max(1, ttl_seconds)),
    )
    return DeployPreparation(
        request,
        "Deploy confirmation required.\n"
        f"Current: {current_commit} · {current_commit_date}\n"
        f"Target: {target_commit} · {target_commit_date}\n"
        f"Description: {escape(target_description)}\n"
        "Confirm to queue the fixed production deploy.",
        "pending",
    )


def apply_deploy_callback(
    *,
    request_id: int,
    action: str,
    telegram_user_id: int,
    chat_id: int,
) -> DeployActionResult:
    with transaction.atomic():
        request = TelegramDeployRequest.objects.select_for_update().filter(pk=request_id).first()
        if request is None or request.telegram_user_id != telegram_user_id or request.chat_id != chat_id:
            return DeployActionResult(None, "This deploy confirmation is not available.", "not_found")
        if request.status != TelegramDeployRequestStatus.PENDING:
            return DeployActionResult(request, "This deploy confirmation was already processed.", "already_processed")
        if timezone.now() > request.expires_at:
            request.status = TelegramDeployRequestStatus.EXPIRED
            request.decided_at = timezone.now()
            request.save(update_fields=["status", "decided_at"])
            return DeployActionResult(request, "Deploy confirmation expired. Run /deploy again.", "expired")
        if action == "cancel":
            request.status = TelegramDeployRequestStatus.CANCELED
            request.decided_at = timezone.now()
            request.save(update_fields=["status", "decided_at"])
            return DeployActionResult(request, "Deploy canceled.", "canceled")
        if action != "confirm":
            return DeployActionResult(request, "This deploy action is not available.", "invalid")
        if not _claim_deploy_request():
            request.status = TelegramDeployRequestStatus.BUSY
            request.decided_at = timezone.now()
            request.save(update_fields=["status", "decided_at"])
            return DeployActionResult(request, "Deploy is already queued, waiting, or running.", "busy")
        if not _start_deploy_service():
            _release_deploy_request()
            request.status = TelegramDeployRequestStatus.FAILED
            request.decided_at = timezone.now()
            request.save(update_fields=["status", "decided_at"])
            return DeployActionResult(request, "Could not queue deploy. Check the Telegram bot logs.", "failed")
        request.status = TelegramDeployRequestStatus.QUEUED
        request.decided_at = timezone.now()
        request.save(update_fields=["status", "decided_at"])
        return DeployActionResult(
            request,
            "Deploy queued. You will receive start and completion notifications.\n"
            f"Commit: <code>{escape(request.target_commit)}</code>\n"
            f"Description: {escape(request.target_description or 'unavailable')}",
            "queued",
        )


def current_queue_status() -> str | None:
    try:
        value = QUEUE_STATUS_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value[:120] or None


def _deploy_commits(branch: str) -> tuple[str | None, str | None]:
    current = _git_output("rev-parse", "--short", "HEAD")
    target = _git_output("ls-remote", "--exit-code", "origin", f"refs/heads/{branch}")
    target_sha = target.split()[0][:12] if target else ""
    return (current or None, target_sha or None)


def _commit_date(revision: str) -> str:
    return _git_output(
        "show",
        "-s",
        "--format=%cd",
        "--date=format-local:%d.%m.%Y %H:%M",
        revision,
    ) or "date unavailable"


def _target_commit_description(*, branch: str, revision: str) -> str:
    """Fetch only the configured production ref so its immutable subject is exact."""
    _git_output("fetch", "--quiet", "--no-tags", "origin", branch)
    return (_git_output("show", "-s", "--format=%s", revision) or "description unavailable")[:255]


def _git_output(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=Path(settings.BASE_DIR),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _claim_deploy_request() -> bool:
    try:
        fd = os.open(DEPLOY_REQUEST_MARKER, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as marker:
        marker.write(str(os.getpid()))
    return True


def _release_deploy_request() -> None:
    try:
        DEPLOY_REQUEST_MARKER.unlink()
    except FileNotFoundError:
        pass


def _start_deploy_service() -> bool:
    try:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "--no-block", "start", DEPLOY_SERVICE],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
