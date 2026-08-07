#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_COMMAND="${JOBAPPLY_DEPLOY_COMMAND:-/usr/local/sbin/jobapply-deploy}"
REQUEST_MARKER="${JOBAPPLY_DEPLOY_REQUEST_MARKER:-/run/jobapply/deploy.requested}"
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
    --data-urlencode "parse_mode=HTML" \
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

send_telegram "$(printf '⏳ <b>JobApply deploy started</b>\n\n🌍 Environment: <b>%s</b>\n🔖 Commit before deploy: <code>%s</code>\n⏱ Estimated time: <b>3–10 minutes</b>' "$ENV_LABEL" "$START_COMMIT")"

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
  send_telegram "$(printf '%s <b>JobApply deploy finished</b>\n\n📦 Result: <b>%s</b>\n🔖 Commit: <code>%s</code>\n⏱ Duration: <b>%s</b>' "$icon" "$result" "$end_commit" "$duration")"
else
  failed_tests="$(sed -nE 's/^FAILED ([^ ]+).*/• \1/p' "$LOG_FILE" | head -n 5 || true)"
  if [[ -n "$failed_tests" ]]; then
    send_telegram "$(printf '❌ <b>JobApply deploy failed: TESTS FAILED</b>\n\n🔢 Exit code: <code>%s</code>\n🔖 Commit: <code>%s</code>\n⏱ Duration: <b>%s</b>\n\n<b>Failed tests:</b>\n%s\n\n🛠 <b>Copy and run on the server:</b>\n<pre><code>tail -n 250 /var/log/jobapply/deploy-last.log</code></pre>' "$status" "$end_commit" "$duration" "$failed_tests")"
  else
    send_telegram "$(printf '❌ <b>JobApply deploy failed</b>\n\n🔢 Exit code: <code>%s</code>\n🔖 Commit: <code>%s</code>\n⏱ Duration: <b>%s</b>\n\n🛠 <b>Copy and run on the server:</b>\n<pre><code>tail -n 250 /var/log/jobapply/deploy-last.log</code></pre>' "$status" "$end_commit" "$duration")"
  fi
fi

exit "$status"
