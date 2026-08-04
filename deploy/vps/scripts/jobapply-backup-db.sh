#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/jobapply}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/jobapply}"
DATABASE_URL="${DATABASE_URL:-}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"
BACKUP_HEARTBEAT_INTERVAL_SECONDS="${BACKUP_HEARTBEAT_INTERVAL_SECONDS:-86400}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_DIR/.venv/bin/python}"

log() {
    printf '[%s] %s\n' "$(date -Is)" "$*"
}

record_backup_heartbeat() {
    local outcome="$1"
    local args=(
        "$PYTHON_BIN" "$PROJECT_DIR/manage.py" record_worker_heartbeat backup_worker
        --interval "$BACKUP_HEARTBEAT_INTERVAL_SECONDS"
    )
    if [[ "$outcome" == "success" ]]; then
        args+=(--success)
    else
        args+=(--failure --error-category BackupFailed)
    fi
    "${args[@]}" || log "WARNING: backup heartbeat update failed"
}

fail() {
    log "ERROR: $*" >&2
    exit 1
}

on_exit() {
    local status=$?
    rm -f "${TMP_FILE:-}"
    if [[ $status -eq 0 ]]; then
        record_backup_heartbeat success
    else
        record_backup_heartbeat failure
    fi
    exit "$status"
}
trap on_exit EXIT

[[ -n "$DATABASE_URL" ]] || fail "DATABASE_URL is not configured"
install -d -m 700 "$BACKUP_DIR"

TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
DUMP_FILE="$BACKUP_DIR/jobapply_${TIMESTAMP}.dump"
TMP_FILE="${DUMP_FILE}.tmp"

log "Creating PostgreSQL dump"
pg_dump \
    --dbname="$DATABASE_URL" \
    --format=custom \
    --compress=6 \
    --no-owner \
    --no-privileges \
    --file="$TMP_FILE"

[[ -s "$TMP_FILE" ]] || fail "database dump is empty"
pg_restore --list "$TMP_FILE" >/dev/null
mv "$TMP_FILE" "$DUMP_FILE"
chmod 600 "$DUMP_FILE"

find "$BACKUP_DIR" -type f -name 'jobapply_*.dump' -mtime +7 -delete

if [[ -n "$RCLONE_REMOTE" ]]; then
    log "Copying dump to $RCLONE_REMOTE"
    rclone copy "$DUMP_FILE" "$RCLONE_REMOTE"
else
    log "RCLONE_REMOTE is empty; remote copy skipped"
fi

log "Backup completed: $DUMP_FILE"
