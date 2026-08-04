#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/jobapply}"
WORK_DIR="${WORK_DIR:-/var/backups/jobapply/neon-sync}"
DATABASE_URL="${DATABASE_URL:-}"
BACKUP_DATABASE_URL="${BACKUP_DATABASE_URL:-}"

log() {
    printf '[%s] %s\n' "$(date -Is)" "$*"
}

fail() {
    log "ERROR: $*" >&2
    exit 1
}

if [[ -z "$BACKUP_DATABASE_URL" ]]; then
    log "BACKUP_DATABASE_URL is empty; Neon sync skipped"
    exit 0
fi

[[ -n "$DATABASE_URL" ]] || fail "DATABASE_URL is not configured"
[[ "$DATABASE_URL" != "$BACKUP_DATABASE_URL" ]] || fail "source and backup database URLs must differ"
[[ "$BACKUP_DATABASE_URL" != *-pooler.* ]] || fail "use a direct Neon PostgreSQL endpoint, not a pooled endpoint"

install -d -m 700 "$WORK_DIR"
DUMP_FILE="$(mktemp "$WORK_DIR/.jobapply-neon-sync.XXXXXX.dump.tmp")"

cleanup() {
    rm -f "$DUMP_FILE"
}
trap cleanup EXIT

log "Creating a consistent dump of the local database"
pg_dump \
    --dbname="$DATABASE_URL" \
    --format=custom \
    --compress=6 \
    --no-owner \
    --no-privileges \
    --file="$DUMP_FILE"

[[ -s "$DUMP_FILE" ]] || fail "database dump is empty"
pg_restore --list "$DUMP_FILE" >/dev/null

log "Replacing the Neon recovery database"
pg_restore \
    --dbname="$BACKUP_DATABASE_URL" \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    --single-transaction \
    --exit-on-error \
    "$DUMP_FILE"

SOURCE_MIGRATIONS="$(psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -tAc 'SELECT COUNT(*) FROM django_migrations;')"
BACKUP_MIGRATIONS="$(psql "$BACKUP_DATABASE_URL" -X -v ON_ERROR_STOP=1 -tAc 'SELECT COUNT(*) FROM django_migrations;')"

[[ "$SOURCE_MIGRATIONS" = "$BACKUP_MIGRATIONS" ]] || \
    fail "migration count mismatch: source=$SOURCE_MIGRATIONS backup=$BACKUP_MIGRATIONS"

log "Neon recovery database synchronized (django_migrations=$BACKUP_MIGRATIONS)"
