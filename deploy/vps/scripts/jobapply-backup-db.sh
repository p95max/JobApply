#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/jobapply}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/jobapply}"
DATABASE_URL="${DATABASE_URL:-}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"

log() {
    printf '[%s] %s\n' "$(date -Is)" "$*"
}

fail() {
    log "ERROR: $*" >&2
    exit 1
}

[[ -n "$DATABASE_URL" ]] || fail "DATABASE_URL is not configured"
install -d -m 700 "$BACKUP_DIR"

TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
DUMP_FILE="$BACKUP_DIR/jobapply_${TIMESTAMP}.dump"
TMP_FILE="${DUMP_FILE}.tmp"

cleanup() {
    rm -f "$TMP_FILE"
}
trap cleanup EXIT

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
