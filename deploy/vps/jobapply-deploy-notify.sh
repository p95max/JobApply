#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_COMMAND="${JOBAPPLY_DEPLOY_COMMAND:-/usr/local/sbin/jobapply-deploy}"
REQUEST_MARKER="${JOBAPPLY_DEPLOY_REQUEST_MARKER:-/var/tmp/jobapply-deploy.requested}"
ENV_LABEL="${TELEGRAM_ENV_LABEL:-PRODUCTION}"
TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT_ID="${TELEGRAM_DEFAULT_CHAT_ID:-}"
STARTED_AT="$(date +%s)"
START_COMMIT="$(git -C /opt/jobapply rev-parse --short HEAD 2>/dev/null || echo unknown)"

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

send_telegram "⏳ JobApply deploy started (${ENV_LABEL}).\nCommit before deploy: ${START_COMMIT}\nEstimated time: about 3–10 minutes."

set +e
"$DEPLOY_COMMAND"
status=$?
set -e

finished_at="$(date +%s)"
duration="$(format_duration $((finished_at - STARTED_AT)))"
end_commit="$(git -C /opt/jobapply rev-parse --short HEAD 2>/dev/null || echo unknown)"

if (( status == 0 )); then
  if [[ "$START_COMMIT" == "$end_commit" ]]; then
    result="UP TO DATE"
    icon="ℹ️"
  else
    result="UPDATED"
    icon="✅"
  fi
  send_telegram "${icon} JobApply deploy finished: ${result}.\nCommit: ${end_commit}\nDuration: ${duration}."
else
  send_telegram "❌ JobApply deploy FAILED.\nExit code: ${status}\nCommit: ${end_commit}\nDuration: ${duration}.\nCheck: journalctl -u jobapply-deploy.service"
fi

exit "$status"
