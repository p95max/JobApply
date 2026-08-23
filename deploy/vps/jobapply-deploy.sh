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
SYSTEMD_DIR="/etc/systemd/system"
STATE_DIR="${JOBAPPLY_DEPLOY_STATE_DIR:-/var/lib/jobapply}"
LAST_SUCCESSFUL_FILE="$STATE_DIR/last-successful-commit"
PREVIOUS_SUCCESSFUL_FILE="$STATE_DIR/previous-successful-commit"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root: sudo $0" >&2
  exit 1
fi

for command in git psql systemctl curl; do
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

record_success() {
  local new_commit old_commit=""
  new_commit="$(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse HEAD)"
  install -d -o root -g jobapply -m 0750 "$STATE_DIR"
  install -d -o root -g jobapply -m 0770 "$STATE_DIR/runtime"
  if [[ -f "$LAST_SUCCESSFUL_FILE" ]]; then
    old_commit="$(tr -d '[:space:]' <"$LAST_SUCCESSFUL_FILE")"
  fi
  if [[ "$old_commit" =~ ^[0-9a-fA-F]{40}$ ]] && [[ "$old_commit" != "$new_commit" ]]; then
    printf '%s\n' "$old_commit" >"$PREVIOUS_SUCCESSFUL_FILE.tmp"
    chown root:jobapply "$PREVIOUS_SUCCESSFUL_FILE.tmp"
    chmod 0640 "$PREVIOUS_SUCCESSFUL_FILE.tmp"
    mv -f "$PREVIOUS_SUCCESSFUL_FILE.tmp" "$PREVIOUS_SUCCESSFUL_FILE"
  fi
  printf '%s\n' "$new_commit" >"$LAST_SUCCESSFUL_FILE.tmp"
  chown root:jobapply "$LAST_SUCCESSFUL_FILE.tmp"
  chmod 0640 "$LAST_SUCCESSFUL_FILE.tmp"
  mv -f "$LAST_SUCCESSFUL_FILE.tmp" "$LAST_SUCCESSFUL_FILE"
}

[[ "$BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]] || {
  echo "Invalid production branch name." >&2
  exit 1
}

current_branch="$(sudo -u "$APP_USER" git -C "$APP_DIR" branch --show-current)"
[[ "$current_branch" == "$BRANCH" ]] || {
  echo "Refusing deploy: HEAD must remain on $BRANCH (currently $current_branch)." >&2
  exit 1
}

[[ -z "$(sudo -u "$APP_USER" git -C "$APP_DIR" status --porcelain --untracked-files=all)" ]] || {
  echo "Refusing deploy: production working tree has local changes." >&2
  exit 1
}

echo "==> Fetching production branch: $BRANCH"
sudo -u "$APP_USER" git -C "$APP_DIR" fetch origin "$BRANCH"
current_commit="$(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short HEAD)"
target_commit="$(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short "origin/$BRANCH")"
current_commit_date="$(sudo -u "$APP_USER" git -C "$APP_DIR" log -1 --format=%cd --date=format-local:'%d.%m.%Y %H:%M' HEAD)"
target_commit_date="$(sudo -u "$APP_USER" git -C "$APP_DIR" log -1 --format=%cd --date=format-local:'%d.%m.%Y %H:%M' "origin/$BRANCH")"
echo "==> Current commit: $current_commit ($current_commit_date)"
echo "==> Target commit:  $target_commit ($target_commit_date)"

sudo -u "$APP_USER" git -C "$APP_DIR" merge-base --is-ancestor HEAD "origin/$BRANCH" || {
  echo "Refusing deploy: update is not fast-forward only." >&2
  exit 1
}
sudo -u "$APP_USER" git -C "$APP_DIR" merge --ff-only "origin/$BRANCH"

echo "==> Synchronizing deploy operations scripts"
install -o root -g jobapply -m 0750 "$APP_DIR/deploy/vps/jobapply-deploy-notify.sh" /usr/local/bin/jobapply-deploy-notify.sh
install -o root -g jobapply -m 0750 "$APP_DIR/deploy/vps/scripts/jobapply-telegram-bot-failure-notify" /usr/local/bin/jobapply-telegram-bot-failure-notify
install -o root -g jobapply -m 0750 "$APP_DIR/deploy/vps/jobapply-deploy.sh" /usr/local/sbin/jobapply-deploy
install -o root -g jobapply -m 0750 "$APP_DIR/deploy/vps/jobapply-rollback.sh" /usr/local/sbin/jobapply-rollback

echo "==> Synchronizing Telegram/deploy systemd units"
install -m 0644 "$APP_DIR/deploy/vps/systemd/jobapply-telegram-bot.service" "$APP_DIR/deploy/vps/systemd/jobapply-deploy.service" "$SYSTEMD_DIR/"

echo "==> Synchronizing scheduled JobApply timers"
install -m 0644 \
  "$APP_DIR/deploy/vps/systemd/jobapply-demo-cleanup.service" \
  "$APP_DIR/deploy/vps/systemd/jobapply-demo-cleanup.timer" \
  "$APP_DIR/deploy/vps/systemd/jobapply-ai-usage-digest.service" \
  "$APP_DIR/deploy/vps/systemd/jobapply-ai-usage-digest.timer" \
  "$APP_DIR/deploy/vps/systemd/jobapply-client-digest.service" \
  "$APP_DIR/deploy/vps/systemd/jobapply-client-digest.timer" \
  "$SYSTEMD_DIR/"
systemctl daemon-reload
systemctl enable --now jobapply-demo-cleanup.timer jobapply-ai-usage-digest.timer jobapply-client-digest.timer

echo "==> Installing locked project dependencies"
cd "$APP_DIR"
if command -v poetry >/dev/null 2>&1; then
  sudo -u "$APP_USER" env POETRY_VIRTUALENVS_CREATE=false VIRTUAL_ENV="$APP_DIR/.venv" PATH="$APP_DIR/.venv/bin:$PATH" poetry install --with dev --no-root --sync
else
  sudo -u "$APP_USER" "$PYTHON" -m pip install --disable-pip-version-check "." pytest-django
fi

echo "==> Ensuring Gunicorn ${GUNICORN_VERSION} is installed"
sudo -u "$APP_USER" "$PYTHON" -m pip install --disable-pip-version-check "gunicorn==${GUNICORN_VERSION}"
[[ -x "$APP_DIR/.venv/bin/gunicorn" ]] || { echo "Gunicorn executable is missing after dependency installation." >&2; exit 1; }

echo "==> Granting temporary CREATEDB permission for pytest"
sudo -u "$DB_ADMIN" psql -v ON_ERROR_STOP=1 -c "ALTER ROLE \"$DB_USER\" CREATEDB;"
createdb_granted=1

echo "==> Running full test suite"
sudo -u "$APP_USER" env DJANGO_SETTINGS_MODULE=config.settings "$PYTHON" -m pytest -ra
cleanup

echo "==> Running Django checks"
run_django check --deploy

echo "==> Applying migrations"
run_django migrate --noinput

echo "==> Collecting static files"
run_django collectstatic --noinput

echo "==> Compiling German translations"
run_django compilemessages -l de

echo "==> Cleaning expired demo accounts"
systemctl start jobapply-demo-cleanup.service

services=(jobapply-web.service jobapply-gmail-assistant.service jobapply-gmail-worker.service jobapply-drive-backup-worker.service jobapply-telegram-bot.service)
installed_services=()
for service in "${services[@]}"; do
  if systemctl cat "$service" >/dev/null 2>&1; then installed_services+=("$service"); fi
done
[[ "${#installed_services[@]}" -gt 0 ]] || { echo "No JobApply systemd services were found; deployment completed without restart." >&2; exit 0; }

echo "==> Restarting services"
systemctl restart "${installed_services[@]}"

echo "==> Verifying services"
for service in "${installed_services[@]}"; do
  systemctl is-active --quiet "$service" || { systemctl --no-pager --full status "$service" || true; echo "Service failed after deployment: $service" >&2; exit 1; }
  echo "  active: $service"
done

for timer in jobapply-demo-cleanup.timer jobapply-ai-usage-digest.timer jobapply-client-digest.timer; do
  systemctl is-enabled --quiet "$timer" || { echo "Required timer is not enabled: $timer" >&2; exit 1; }
done

echo "==> Running HTTP health check"
curl --fail --silent --show-error --max-time 10 "$HEALTH_URL" >/dev/null

echo "==> Recording successful production commit"
record_success

echo
final_commit="$(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short HEAD)"
final_commit_date="$(sudo -u "$APP_USER" git -C "$APP_DIR" log -1 --format=%cd --date=format-local:'%d.%m.%Y %H:%M' HEAD)"
echo "Deployment completed successfully at commit: $final_commit ($final_commit_date)"
