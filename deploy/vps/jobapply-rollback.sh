#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/jobapply}"
APP_USER="${APP_USER:-jobapply}"
DB_ADMIN="${DB_ADMIN:-postgres}"
DB_USER="${DB_USER:-jobapply}"
BRANCH="${JOBAPPLY_PRODUCTION_BRANCH:-master}"
PYTHON="${PYTHON:-$APP_DIR/.venv/bin/python}"
MANAGE="$APP_DIR/manage.py"
GUNICORN_VERSION="${GUNICORN_VERSION:-26.0.0}"
HEALTH_URL="${JOBAPPLY_HEALTH_URL:-http://127.0.0.1/}"
TARGET_COMMIT="${1:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

[[ "$TARGET_COMMIT" =~ ^[0-9a-fA-F]{7,40}$ ]] || {
  echo "Invalid rollback commit." >&2
  exit 1
}

[[ -x "$PYTHON" ]] || {
  echo "Python virtual environment not found: $PYTHON" >&2
  exit 1
}

[[ -z "$(sudo -u "$APP_USER" git -C "$APP_DIR" status --porcelain --untracked-files=all)" ]] || {
  echo "Refusing rollback: production working tree has local changes." >&2
  exit 1
}

current_branch="$(sudo -u "$APP_USER" git -C "$APP_DIR" branch --show-current)"
[[ "$current_branch" == "$BRANCH" ]] || {
  echo "Refusing rollback: HEAD must remain on $BRANCH (currently $current_branch)." >&2
  exit 1
}

echo "==> Fetching production branch: $BRANCH"
sudo -u "$APP_USER" git -C "$APP_DIR" fetch --quiet origin "$BRANCH"

sudo -u "$APP_USER" git -C "$APP_DIR" cat-file -e "${TARGET_COMMIT}^{commit}" || {
  echo "Rollback target does not exist: $TARGET_COMMIT" >&2
  exit 1
}

sudo -u "$APP_USER" git -C "$APP_DIR" merge-base --is-ancestor "$TARGET_COMMIT" "origin/$BRANCH" || {
  echo "Refusing rollback: target is not an ancestor of origin/$BRANCH." >&2
  exit 1
}

current_commit="$(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short HEAD)"
target_commit="$(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short "$TARGET_COMMIT")"
echo "==> Rolling back application code: $current_commit -> $target_commit"
sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard "$TARGET_COMMIT"

createdb_granted=0
cleanup() {
  if [[ "$createdb_granted" -eq 1 ]]; then
    echo "==> Revoking temporary CREATEDB permission"
    sudo -u "$DB_ADMIN" psql -v ON_ERROR_STOP=1 \
      -c "ALTER ROLE \"$DB_USER\" NOCREATEDB;" || true
    createdb_granted=0
  fi
}
trap cleanup EXIT INT TERM

run_django() {
  sudo -u "$APP_USER" env DJANGO_SETTINGS_MODULE=config.settings "$PYTHON" "$MANAGE" "$@"
}

echo "==> Installing dependencies for rollback target"
cd "$APP_DIR"
if command -v poetry >/dev/null 2>&1; then
  sudo -u "$APP_USER" env \
    POETRY_VIRTUALENVS_CREATE=false \
    VIRTUAL_ENV="$APP_DIR/.venv" \
    PATH="$APP_DIR/.venv/bin:$PATH" \
    poetry install --with dev --no-root --sync
else
  sudo -u "$APP_USER" "$PYTHON" -m pip install --disable-pip-version-check "." pytest-django
fi
sudo -u "$APP_USER" "$PYTHON" -m pip install --disable-pip-version-check "gunicorn==${GUNICORN_VERSION}"

[[ -x "$APP_DIR/.venv/bin/gunicorn" ]] || {
  echo "Gunicorn executable is missing after dependency installation." >&2
  exit 1
}

echo "==> Granting temporary CREATEDB permission for pytest"
sudo -u "$DB_ADMIN" psql -v ON_ERROR_STOP=1 -c "ALTER ROLE \"$DB_USER\" CREATEDB;"
createdb_granted=1

echo "==> Running full test suite for rollback target"
sudo -u "$APP_USER" env DJANGO_SETTINGS_MODULE=config.settings "$PYTHON" -m pytest -ra
cleanup

echo "==> Running Django checks"
run_django check --deploy

# Intentionally forward-only. Extra newer schema is retained; rollback never
# runs reverse migrations automatically because they may destroy production data.
echo "==> Applying forward-safe migrations only"
run_django migrate --noinput

echo "==> Collecting static files"
run_django collectstatic --noinput

echo "==> Compiling German translations"
run_django compilemessages -l de

services=(
  jobapply-web.service
  jobapply-gmail-assistant.service
  jobapply-gmail-worker.service
  jobapply-drive-backup-worker.service
  jobapply-telegram-bot.service
)
installed_services=()
for service in "${services[@]}"; do
  if systemctl cat "$service" >/dev/null 2>&1; then
    installed_services+=("$service")
  fi
done

[[ "${#installed_services[@]}" -gt 0 ]] || {
  echo "No JobApply systemd services were found." >&2
  exit 1
}

echo "==> Restarting services"
systemctl restart "${installed_services[@]}"

for service in "${installed_services[@]}"; do
  systemctl is-active --quiet "$service" || {
    systemctl --no-pager --full status "$service" || true
    echo "Service failed after rollback: $service" >&2
    exit 1
  }
done

echo "==> Running HTTP health check"
curl --fail --silent --show-error --max-time 10 "$HEALTH_URL" >/dev/null

echo "Rollback completed successfully at commit: $(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short HEAD)"
