#!/usr/bin/env bash
# [review:need-review] PHASE-03/96
# summary: weekly run of app.exports.personal_os — the finished week written back out as `plans/YYYY/MM/*.md` into a week-named archive folder, so the rollback ADR-0014 prices at 1-2 weeks stays payable
#
# Cron on the VPS (Monday morning, after the nightly dump):
#   15 4 * * 1 /opt/habit-tracker/deploy/export-md.sh >> /var/log/habit-backup.log 2>&1
#
# This is not a feature, it is the price of the rollback. The dump restores the
# database into this application; the export is what a human can read, and what
# a return to the file mode would be rebuilt from. Without it the `.md` plans
# left in `personal-os` go stale within a month and the rollback loses
# everything accumulated since the switch (ADR-0014, «Reversal cost»).
#
# Two paths, one directory. The exporter runs inside the backend container and
# writes to CONTAINER_OUT; the host sees the same bytes at ARCHIVE_DIR because
# `deploy/docker-compose.prod.yml` bind-mounts BACKUP_DIR to /backups. Change
# one of the three and change the other two.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/habit-tracker/backups}"
ARCHIVE_DIR="${ARCHIVE_DIR:-$BACKUP_DIR/exports}"
CONTAINER_OUT="${CONTAINER_OUT:-/backups/exports}"
# `last` is the week that finished — never the one still being lived.
WEEK="${WEEK:-last}"
STATUS_FILE="${STATUS_FILE:-$ARCHIVE_DIR/export-status}"
# Overridable so the tests can drive the script without docker.
EXPORT_CMD="${EXPORT_CMD:-docker exec habit_backend python -m app.exports.personal_os}"

on_exit() {
  code=$?
  if [ "$code" -ne 0 ]; then
    printf '%s FAIL exit=%s week=%s\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$code" "$WEEK" >"$STATUS_FILE" || true
    echo "export-md FAILED (exit $code); status: $STATUS_FILE" >&2
  fi
  exit "$code"
}
trap on_exit EXIT

mkdir -p "$ARCHIVE_DIR"

# The exporter exits non-zero when a week produced no files at all, which is the
# shape "the export is pointed at the wrong database" takes.
# shellcheck disable=SC2086 # EXPORT_CMD is a command line; splitting is the point
$EXPORT_CMD --out "$CONTAINER_OUT" --week "$WEEK"

printf '%s OK week=%s out=%s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$WEEK" "$ARCHIVE_DIR" >"$STATUS_FILE"
echo "export-md done: $ARCHIVE_DIR (week $WEEK)"
