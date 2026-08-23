#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_COMMAND="${JOBAPPLY_DEPLOY_COMMAND:-/usr/local/sbin/jobapply-deploy}"
ROLLBACK_COMMAND="${JOBAPPLY_ROLLBACK_COMMAND:-/usr/local/sbin/jobapply-rollback}"
REQUEST_MARKER="${JOBAPPLY_DEPLOY_REQUEST_MARKER:-/var/lib/jobapply/runtime/deploy.requested}"
STATE_DIR="${JOBAPPLY_DEPLOY_STATE_DIR:-/var/lib/jobapply}"
LAST_SUCCESSFUL_FILE="$STATE_DIR/last-successful-commit"
PREVIOUS_SUCCESSFUL_FILE="$STATE_DIR/previous-successful-commit"
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

get_commit_full() {
  sudo -u jobapply git -C /opt/jobapply rev-parse HEAD 2>/dev/null || echo unknown
}

get_commit_date() {
  sudo -u jobapply git -C /opt/jobapply log -1 --format=%cd --date=format-local:'%d.%m.%Y %H:%M' HEAD 2>/dev/null || echo unknown
}

is_sha() {
  [[ "$1" =~ ^[0-9a-fA-F]{7,40}$ ]]
}

record_success() {
  local new_commit="$1"
  local old_commit=""
  is_sha "$new_commit" || return 1
  install -d -o root -g jobapply -m 0750 "$STATE_DIR"
  if [[ -f "$LAST_SUCCESSFUL_FILE" ]]; then
    old_commit="$(tr -d '[:space:]' <"$LAST_SUCCESSFUL_FILE")"
  fi
  if is_sha "$old_commit" && [[ "$old_commit" != "$new_commit" ]]; then
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

OPERATION="deploy"
TARGET_COMMIT=""
if [[ -f "$REQUEST_MARKER" ]]; then
  read -r marker_operation marker_target <"$REQUEST_MARKER" || true
  if [[ "$marker_operation" == "rollback" ]] && is_sha "${marker_target:-}"; then
    OPERATION="rollback"
    TARGET_COMMIT="$marker_target"
  elif [[ "$marker_operation" == "deploy" ]] && is_sha "${marker_target:-}"; then
    OPERATION="deploy"
    TARGET_COMMIT="$marker_target"
  fi
fi

START_COMMIT="$(get_commit)"
START_COMMIT_DATE="$(get_commit_date)"
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

if [[ "$OPERATION" == "rollback" ]]; then
  send_telegram "$(printf '⏳ <b>JobApply rollback started</b>\n\n🌍 Environment: <b>%s</b>\n🔖 Current commit: <code>%s</code>\n↩️ Target commit: <code>%s</code>\n⏱ Estimated time: <b>3–10 minutes</b>' "$ENV_LABEL" "$START_COMMIT" "${TARGET_COMMIT:0:12}")"
else
  send_telegram "$(printf '⏳ <b>JobApply deploy started</b>\n\n🌍 Environment: <b>%s</b>\n🔖 Commit before deploy: <code>%s</code>\n📅 Commit date: <code>%s</code>\n⏱ Estimated time: <b>3–10 minutes</b>' "$ENV_LABEL" "$START_COMMIT" "$START_COMMIT_DATE")"
fi

set +e
if [[ "$OPERATION" == "rollback" ]]; then
  "$ROLLBACK_COMMAND" "$TARGET_COMMIT" >"$LOG_FILE" 2>&1
else
  "$DEPLOY_COMMAND" >"$LOG_FILE" 2>&1
fi
status=$?
set -e
tail -n 40 "$LOG_FILE" >"$TAIL_FILE" || true

finished_at="$(date +%s)"
duration="$(format_duration $((finished_at - STARTED_AT)))"
end_commit="$(get_commit)"
end_commit_full="$(get_commit_full)"
end_commit_date="$(get_commit_date)"
printf 'operation=%s\nexit_code=%s\nstart_commit=%s\nstart_commit_date=%s\nend_commit=%s\nend_commit_date=%s\nduration=%s\n' \
  "$OPERATION" "$status" "$START_COMMIT" "$START_COMMIT_DATE" "$end_commit" "$end_commit_date" "$duration" >"$STATUS_FILE"

if (( status == 0 )); then
  record_success "$end_commit_full"
  if [[ "$OPERATION" == "rollback" ]]; then
    send_telegram "$(printf '🟢 <b>JobApply rollback finished</b>\n\n↩️ Rolled back: <code>%s</code> → <code>%s</code>\n📅 Commit date: <code>%s</code>\n⏱ Duration: <b>%s</b>\n\nDatabase migrations were not reversed.' "$START_COMMIT" "$end_commit" "$end_commit_date" "$duration")"
  else
    if [[ "$START_COMMIT" == "$end_commit" ]]; then
      result="UP TO DATE"
      icon="🟡"
    else
      result="UPDATED"
      icon="🟢"
    fi
    send_telegram "$(printf '%s <b>JobApply deploy finished</b>\n\n📦 Result: <b>%s</b>\n🔖 Commit: <code>%s</code>\n📅 Commit date: <code>%s</code>\n⏱ Duration: <b>%s</b>' "$icon" "$result" "$end_commit" "$end_commit_date" "$duration")"
  fi
else
  failed_tests="$(sed -nE 's/^FAILED ([^ ]+).*/\1/p' "$LOG_FILE" | head -n 5 | sed 's/::/\n  ↳ /' || true)"
  label="deploy"
  [[ "$OPERATION" == "rollback" ]] && label="rollback"
  if [[ -n "$failed_tests" ]]; then
    send_telegram "$(printf '🔴 <b>JobApply %s failed: TESTS FAILED</b>\n\n🔢 Exit code: <code>%s</code>\n🔖 Commit: <code>%s</code>\n📅 Commit date: <code>%s</code>\n⏱ Duration: <b>%s</b>\n\n<b>Failed tests:</b>\n<pre><code>%s</code></pre>\n\n🛠 <b>Copy and run on the server:</b>\n<pre><code>tail -n 250 /var/log/jobapply/deploy-last.log</code></pre>' "$label" "$status" "$end_commit" "$end_commit_date" "$duration" "$failed_tests")"
  else
    send_telegram "$(printf '🔴 <b>JobApply %s failed</b>\n\n🔢 Exit code: <code>%s</code>\n🔖 Commit: <code>%s</code>\n📅 Commit date: <code>%s</code>\n⏱ Duration: <b>%s</b>\n\n🛠 <b>Copy and run on the server:</b>\n<pre><code>tail -n 250 /var/log/jobapply/deploy-last.log</code></pre>' "$label" "$status" "$end_commit" "$end_commit_date" "$duration")"
  fi
fi

exit "$status"
