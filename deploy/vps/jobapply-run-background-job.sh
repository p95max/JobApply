#!/usr/bin/env bash
set -Eeuo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

QUEUE_LOCK_FILE="${JOBAPPLY_BACKGROUND_QUEUE_LOCK_FILE:-/tmp/jobapply-background-jobs.lock}"
QUEUE_WAIT_SECONDS="${JOBAPPLY_BACKGROUND_QUEUE_WAIT_SECONDS:-1800}"

if [[ "$#" -lt 2 ]]; then
  echo "Usage: $0 <job-name> <command> [args...]" >&2
  exit 64
fi

JOB_NAME="$1"
shift

case "$JOB_NAME" in
  jobapply-[a-z0-9-]*) ;;
  *)
    echo "Invalid job name: $JOB_NAME" >&2
    exit 64
    ;;
esac

[[ "$QUEUE_WAIT_SECONDS" =~ ^[0-9]+$ ]] || {
  echo "JOBAPPLY_BACKGROUND_QUEUE_WAIT_SECONDS must be an integer" >&2
  exit 64
}

JOB_LOCK_FILE="/tmp/${JOB_NAME}.lock"
exec 8>"$JOB_LOCK_FILE"
if ! flock -n 8; then
  echo "Queue[$JOB_NAME]: duplicate job is already running or waiting; skipping."
  exit 0
fi

started_at="$(date +%s)"
exec 9>"$QUEUE_LOCK_FILE"
echo "Queue[$JOB_NAME]: waiting up to ${QUEUE_WAIT_SECONDS}s for shared lock."

if ! flock -w "$QUEUE_WAIT_SECONDS" 9; then
  echo "Queue[$JOB_NAME]: timed out waiting for $QUEUE_LOCK_FILE" >&2
  exit 75
fi

waited=$(( $(date +%s) - started_at ))
echo "Queue[$JOB_NAME]: acquired shared lock after ${waited}s."
echo "Queue[$JOB_NAME]: starting: $*"

set +e
"$@"
status=$?
set -e

echo "Queue[$JOB_NAME]: finished with exit status $status."
exit "$status"
