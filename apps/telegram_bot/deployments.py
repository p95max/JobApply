from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import timedelta
from html import escape
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import (
    TelegramDeployOperation,
    TelegramDeployRequest,
    TelegramDeployRequestStatus,
)

logger = logging.getLogger(__name__)

DEPLOY_SERVICE = "jobapply-deploy.service"
DEPLOY_REQUEST_MARKER = Path(os.getenv("JOBAPPLY_DEPLOY_REQUEST_MARKER", "/var/tmp/jobapply-deploy.requested"))
QUEUE_STATUS_FILE = Path("/var/tmp/jobapply-background-job.status")
DEPLOY_STATE_DIR = Path(os.getenv("JOBAPPLY_DEPLOY_STATE_DIR", "/var/lib/jobapply"))
LAST_SUCCESSFUL_FILE = DEPLOY_STATE_DIR / "last-successful-commit"
PREVIOUS_SUCCESSFUL_FILE = DEPLOY_STATE_DIR / "previous-successful-commit"


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


@dataclass(frozen=True)
class DeployMenu:
    current_commit: str
    latest_commit: str
    rollback_commit: str | None


def deploy_callback_data(request_id: int, action: str) -> str:
    if action not in {"confirm", "cancel"}:
        raise ValueError("Unsupported deploy action")
    return f"deploy:{request_id}:{action}"


def deploy_menu_callback_data(operation: str) -> str:
    if operation not in {TelegramDeployOperation.DEPLOY, TelegramDeployOperation.ROLLBACK}:
        raise ValueError("Unsupported deploy operation")
    return f"deploymenu:{operation}"


def parse_deploy_menu_callback(value: object) -> str | None:
    if value == "deploymenu:deploy":
        return TelegramDeployOperation.DEPLOY
    if value == "deploymenu:rollback":
        return TelegramDeployOperation.ROLLBACK
    return None


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


def get_deploy_menu(branch: str) -> DeployMenu | None:
    current_commit, latest_commit = _deploy_commits(branch)
    if current_commit is None or latest_commit is None:
        return None
    return DeployMenu(
        current_commit=current_commit,
        latest_commit=latest_commit,
        rollback_commit=_rollback_target(),
    )


def prepare_deploy_request(
    *,
    telegram_user_id: int,
    chat_id: int,
    branch: str,
    ttl_seconds: int,
    operation: str = TelegramDeployOperation.DEPLOY,
) -> DeployPreparation:
    if operation not in {TelegramDeployOperation.DEPLOY, TelegramDeployOperation.ROLLBACK}:
        return DeployPreparation(None, "Unsupported production operation.", "invalid")
    if (busy := current_queue_status()) is not None:
        return DeployPreparation(None, f"A background job is busy: {busy}", "busy")

    current_commit = _git_output("rev-parse", "--short", "HEAD") or None
    if current_commit is None:
        return DeployPreparation(None, "Could not read current production commit.", "failed")

    if operation == TelegramDeployOperation.DEPLOY:
        _current, target_commit = _deploy_commits(branch)
        if target_commit is None:
            return DeployPreparation(None, "Could not read latest production commit.", "failed")
        target_description = _target_commit_description(branch=branch, revision=target_commit)
        title = "Deploy confirmation required."
        final_line = "Confirm to queue the fixed production deploy."
    else:
        target_commit = _rollback_target()
        if target_commit is None:
            return DeployPreparation(
                None,
                "Rollback is not available yet. JobApply needs a previously tracked successful production commit.",
                "unavailable",
            )
        if not _commit_exists(target_commit):
            return DeployPreparation(None, "Tracked rollback commit is not available in the local repository.", "failed")
        target_description = (_git_output("show", "-s", "--format=%s", target_commit) or "previous successful production commit")[:255]
        title = "Rollback confirmation required."
        final_line = "Confirm to roll application code back. Database migrations will not be reversed."

    target_commit_date = _commit_date(target_commit)
    current_commit_date = _commit_date("HEAD")
    request = TelegramDeployRequest.objects.create(
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        current_commit=current_commit,
        target_commit=target_commit,
        target_description=target_description,
        operation=operation,
        expires_at=timezone.now() + timedelta(seconds=max(1, ttl_seconds)),
    )
    return DeployPreparation(
        request,
        f"{title}\n"
        f"Current: {current_commit} · {current_commit_date}\n"
        f"Target: {target_commit[:12]} · {target_commit_date}\n"
        f"Description: {escape(target_description)}\n"
        f"{final_line}",
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
            return DeployActionResult(None, "This production confirmation is not available.", "not_found")
        if request.status != TelegramDeployRequestStatus.PENDING:
            return DeployActionResult(request, "This production confirmation was already processed.", "already_processed")
        if timezone.now() > request.expires_at:
            request.status = TelegramDeployRequestStatus.EXPIRED
            request.decided_at = timezone.now()
            request.save(update_fields=["status", "decided_at"])
            return DeployActionResult(request, "Confirmation expired. Run /deploy again.", "expired")
        if action == "cancel":
            request.status = TelegramDeployRequestStatus.CANCELED
            request.decided_at = timezone.now()
            request.save(update_fields=["status", "decided_at"])
            label = "Rollback" if request.operation == TelegramDeployOperation.ROLLBACK else "Deploy"
            return DeployActionResult(request, f"{label} canceled.", "canceled")
        if action != "confirm":
            return DeployActionResult(request, "This production action is not available.", "invalid")

        claim = _claim_deploy_request(operation=request.operation, target_commit=request.target_commit)
        if claim is None:
            request.status = TelegramDeployRequestStatus.FAILED
            request.decided_at = timezone.now()
            request.save(update_fields=["status", "decided_at"])
            return DeployActionResult(
                request,
                "Could not create the production runtime marker. Check the Telegram bot service configuration.",
                "failed",
            )
        if not claim:
            request.status = TelegramDeployRequestStatus.BUSY
            request.decided_at = timezone.now()
            request.save(update_fields=["status", "decided_at"])
            return DeployActionResult(request, "A deploy or rollback is already queued, waiting, or running.", "busy")
        if not _start_deploy_service():
            _release_deploy_request()
            request.status = TelegramDeployRequestStatus.FAILED
            request.decided_at = timezone.now()
            request.save(update_fields=["status", "decided_at"])
            return DeployActionResult(request, "Could not queue production operation. Check the Telegram bot logs.", "failed")
        request.status = TelegramDeployRequestStatus.QUEUED
        request.decided_at = timezone.now()
        request.save(update_fields=["status", "decided_at"])
        label = "Rollback" if request.operation == TelegramDeployOperation.ROLLBACK else "Deploy"
        return DeployActionResult(
            request,
            f"{label} queued. You will receive start and completion notifications.\n"
            f"Commit: <code>{escape(request.target_commit[:12])}</code>\n"
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
    target_sha = target.split()[0] if target else ""
    return (current or None, target_sha or None)


def _rollback_target() -> str | None:
    current = _git_output("rev-parse", "HEAD")
    last_successful = _read_state_commit(LAST_SUCCESSFUL_FILE)
    previous_successful = _read_state_commit(PREVIOUS_SUCCESSFUL_FILE)
    if not last_successful:
        return None
    if current == last_successful:
        return previous_successful
    return last_successful


def _read_state_commit(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if len(value) != 40 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
        return None
    return value.lower()


def _commit_exists(revision: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
            cwd=Path(settings.BASE_DIR),
            check=False,
            capture_output=True,
            timeout=5,
        )
    except OSError:
        return False
    return result.returncode == 0


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


def _claim_deploy_request(*, operation: str, target_commit: str) -> bool | None:
    """Atomically claim one production operation and pin its immutable target."""
    if operation not in {TelegramDeployOperation.DEPLOY, TelegramDeployOperation.ROLLBACK}:
        return None
    if not target_commit or any(ch not in "0123456789abcdefABCDEF" for ch in target_commit):
        return None
    try:
        DEPLOY_REQUEST_MARKER.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(DEPLOY_REQUEST_MARKER, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    except OSError as error:
        logger.error(
            "Could not claim Telegram deploy marker path=%s error=%s",
            DEPLOY_REQUEST_MARKER,
            type(error).__name__,
        )
        return None
    with os.fdopen(fd, "w", encoding="utf-8") as marker:
        marker.write(f"{operation} {target_commit}\n")
    return True


def _release_deploy_request() -> None:
    try:
        DEPLOY_REQUEST_MARKER.unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        logger.warning(
            "Could not release Telegram deploy marker path=%s error=%s",
            DEPLOY_REQUEST_MARKER,
            type(error).__name__,
        )


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
