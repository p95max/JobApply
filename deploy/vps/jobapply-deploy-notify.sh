#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_COMMAND="${JOBAPPLY_DEPLOY_COMMAND:-/usr/local/sbin/jobapply-deploy}"
REQUEST_MARKER="${JOBAPPLY_DEPLOY_REQUEST_MARKER:-/var/tmp/jobapply-deploy.requested}"
ENV_LABEL="${TELEGRAM_ENV_LABEL:-PRODUCTION}"
TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT_ID="${TELEGRAM_DEFAULT_CHAT_ID:-}"
STARTED_AT="$(date +%s)"
LOG_DIR="${JOBAPPLY_DEPLOY_LOG_DIR:-/var/log/jobapply}"
LOG_FILE="$LOG_DIR/deploy-last.log"
TAIL_FILE="$LOG_DIR/deploy-last-tail.log"
STATUS_FILE="$LOG_DIR/deploy-last.status"

get_commit() {
  sudo -u jobapply git -C /opt/jobapply rev-parse --short HEAD 2>/dev/null || echo unknown
}

START_COMMIT="$(get_commit)"
install -d -m 0750 "$LOG_DIR"

cleanup() {
  rm -f "$REQUEST_MARKER"
}
trap cleanup EXIT INT TERM

send_telegram() {
  local text="$1"
  if [[ -z "$TOKEN" || -z "$CHAT_ID" ]]; then
    echo "Telegram notification skipped: token or chat ID is missing." >&2
    return 0
  fi

  curl --fail --silent --show-error \
    --max-time 10 \
    --data-urlencode "chat_id=$CHAT_ID" \
    --data-urlencode "text=$text" \
    "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    >/dev/null || echo "Telegram notification failed." >&2
}

format_duration() {
  local total="$1"
  local minutes=$((total / 60))
  local seconds=$((total % 60))
  if (( minutes > 0 )); then
    printf '%dm %02ds' "$minutes" "$seconds"
  else
    printf '%ds' "$seconds"
  fi
}

send_telegram "$(printf '⏳ JobApply deploy started (%s).\nCommit before deploy: %s\nEstimated time: about 3–10 minutes.' "$ENV_LABEL" "$START_COMMIT")"

set +e
"$DEPLOY_COMMAND" >"$LOG_FILE" 2>&1
status=$?
set -e
tail -n 40 "$LOG_FILE" >"$TAIL_FILE" || true

finished_at="$(date +%s)"
duration="$(format_duration $((finished_at - STARTED_AT)))"
end_commit="$(get_commit)"
printf 'exit_code=%s\nstart_commit=%s\nend_commit=%s\nduration=%s\n' \
  "$status" "$START_COMMIT" "$end_commit" "$duration" >"$STATUS_FILE"

if (( status == 0 )); then
  if [[ "$START_COMMIT" == "$end_commit" ]]; then
    result="UP TO DATE"
    icon="ℹ️"
  else
    result="UPDATED"
    icon="✅"
  fi
  send_telegram "$(printf '%s JobApply deploy finished: %s.\nCommit: %s\nDuration: %s.' "$icon" "$result" "$end_commit" "$duration")"
else
  send_telegram "$(printf '❌ JobApply deploy FAILED.\nExit code: %s\nCommit: %s\nDuration: %s.\nCheck: journalctl -u jobapply-deploy.service' "$status" "$end_commit" "$duration")"
fi

exit "$status"
