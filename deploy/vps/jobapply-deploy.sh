#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/jobapply}"
APP_USER="${APP_USER:-jobapply}"
DB_ADMIN="${DB_ADMIN:-postgres}"
DB_USER="${DB_USER:-jobapply}"
BRANCH="${BRANCH:-master}"
PYTHON="${PYTHON:-$APP_DIR/.venv/bin/python}"
MANAGE="$APP_DIR/manage.py"
GUNICORN_VERSION="${GUNICORN_VERSION:-26.0.0}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root: sudo $0" >&2
  exit 1
fi

for command in git psql systemctl; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required command not found: $command" >&2
    exit 1
  }
done

[[ -x "$PYTHON" ]] || {
  echo "Python virtual environment not found: $PYTHON" >&2
  exit 1
}

[[ -f "$MANAGE" ]] || {
  echo "manage.py not found: $MANAGE" >&2
  exit 1
}

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
  sudo -u "$APP_USER" env \
    DJANGO_SETTINGS_MODULE=config.settings \
    "$PYTHON" "$MANAGE" "$@"
}

echo "==> Fetching master"
sudo -u "$APP_USER" git -C "$APP_DIR" fetch origin "$BRANCH"
sudo -u "$APP_USER" git -C "$APP_DIR" checkout "$BRANCH"
sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only origin "$BRANCH"

echo "==> Installing locked project dependencies"
cd "$APP_DIR"
if command -v poetry >/dev/null 2>&1; then
  sudo -u "$APP_USER" env \
    POETRY_VIRTUALENVS_CREATE=false \
    VIRTUAL_ENV="$APP_DIR/.venv" \
    PATH="$APP_DIR/.venv/bin:$PATH" \
    poetry install --with dev --no-root --sync
else
  sudo -u "$APP_USER" "$PYTHON" -m pip install \
    --disable-pip-version-check \
    "." pytest-django
fi

# Gunicorn is required by jobapply-web.service. Keep it present even while
# Poetry --sync removes packages that are not yet represented in poetry.lock.
echo "==> Ensuring Gunicorn ${GUNICORN_VERSION} is installed"
sudo -u "$APP_USER" "$PYTHON" -m pip install \
  --disable-pip-version-check \
  "gunicorn==${GUNICORN_VERSION}"

[[ -x "$APP_DIR/.venv/bin/gunicorn" ]] || {
  echo "Gunicorn executable is missing after dependency installation." >&2
  exit 1
}

echo "==> Granting temporary CREATEDB permission for pytest"
sudo -u "$DB_ADMIN" psql -v ON_ERROR_STOP=1 \
  -c "ALTER ROLE \"$DB_USER\" CREATEDB;"
createdb_granted=1

echo "==> Running full test suite"
sudo -u "$APP_USER" env \
  DJANGO_SETTINGS_MODULE=config.settings \
  "$PYTHON" -m pytest -ra

cleanup

echo "==> Running Django checks"
run_django check --deploy

echo "==> Applying migrations"
run_django migrate --noinput

echo "==> Collecting static files"
run_django collectstatic --noinput

echo "==> Compiling German translations"
run_django compilemessages -l de

services=(
  jobapply-web.service
  jobapply-gmail-assistant.service
  jobapply-gmail-worker.service
  jobapply-telegram-bot.service
)
installed_services=()

for service in "${services[@]}"; do
  if systemctl cat "$service" >/dev/null 2>&1; then
    installed_services+=("$service")
  fi
done

if [[ "${#installed_services[@]}" -eq 0 ]]; then
  echo "No JobApply systemd services were found; deployment completed without restart." >&2
  exit 0
fi

echo "==> Restarting services"
systemctl restart "${installed_services[@]}"

echo "==> Verifying services"
for service in "${installed_services[@]}"; do
  systemctl is-active --quiet "$service" || {
    systemctl --no-pager --full status "$service" || true
    echo "Service failed after deployment: $service" >&2
    exit 1
  }
  echo "  active: $service"
done

echo
printf 'Deployment completed successfully at commit: '
sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short HEAD
