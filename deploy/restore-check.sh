#!/usr/bin/env bash
# [review:need-review] PHASE-03/96
# summary: restores the freshest dump into a throwaway database, prints how many days/plans/items/marks came back, and exits non-zero on a stale, broken, secret-carrying or empty backup
#
# Cron on the VPS (weekly, an hour after the nightly dump):
#   30 4 * * 1 /opt/habit-tracker/deploy/restore-check.sh >> /var/log/habit-backup.log 2>&1
#
# A backup nobody restored is not a backup. This script is the difference
# between "pg_dump exited zero" and "the day of 2026-08-28 comes back", and it
# refuses in five separate ways, each of which has actually happened to
# somebody:
#
#   1. no dump at all, or the last one is older than MAX_AGE_HOURS — the cron
#      job died and the status file was never read;
#   2. the last run of `backup.sh` recorded FAIL;
#   3. the dump is not a readable gzip stream;
#   4. the dump carries something that looks like a secret — `deploy/README.md`
#      promises the dump holds no credentials, and a promise nothing checks is
#      a wish;
#   5. the restored database has zero days, which is what a dump of the wrong
#      database or of an empty one looks like.
#
# It leaves nothing behind: the throwaway database is dropped on every exit
# path, including the failing ones.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/habit-tracker/backups}"
STATUS_FILE="${STATUS_FILE:-$BACKUP_DIR/backup-status}"
# A nightly dump older than this means yesterday is already unrecoverable.
MAX_AGE_HOURS="${MAX_AGE_HOURS:-36}"
# Overridable so the tests can drive the script without docker or postgres.
PSQL_CMD="${PSQL_CMD:-docker exec -i habit_postgres psql -U habit_user}"

# Extended regular expressions that must not appear in a dump. Prefixes of real
# credentials, not guesses: `ya29.` and `1//0` are Google OAuth tokens
# (`secrets/gmail_token.json`), `sk-ant-` an Anthropic key, and the environment
# name is how the CLI token reaches the container. Override the whole list with
# SECRET_PATTERNS when a false positive shows up — a plan whose text genuinely
# contains one of these has to fail loudly first.
#
# Assigned in an `if` rather than with `${VAR:-default}`: the default contains
# `{20}`, and the first `}` inside a `${...:-...}` closes the expansion — the
# pattern would silently become `ya29\.[A-Za-z0-9_-]{20` and match nothing.
if [ -z "${SECRET_PATTERNS:-}" ]; then
  SECRET_PATTERNS='ya29\.[A-Za-z0-9_-]{20}|1//0[A-Za-z0-9_-]{20}|sk-ant-[A-Za-z0-9-]{20}|CLAUDE_CODE_OAUTH_TOKEN|-----BEGIN [A-Z ]*PRIVATE KEY-----|telethon\.session'
fi

DUMP=""
KEEP_DB="no"
while [ $# -gt 0 ]; do
  case "$1" in
    --dump)
      DUMP="${2:?--dump needs a path}"
      shift 2
      ;;
    --keep-db)
      KEEP_DB="yes"
      shift
      ;;
    -h | --help)
      echo "usage: restore-check.sh [--dump PATH] [--keep-db]"
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

CHECK_DB="habit_restore_check_$(date +%Y%m%d_%H%M%S)_$$"
DB_CREATED="no"

psql_run() {
  # shellcheck disable=SC2086 # PSQL_CMD is a command line; splitting is the point
  $PSQL_CMD "$@"
}

cleanup() {
  code=$?
  if [ "$DB_CREATED" = "yes" ] && [ "$KEEP_DB" = "no" ]; then
    psql_run -v ON_ERROR_STOP=1 -d postgres \
      -c "DROP DATABASE IF EXISTS \"$CHECK_DB\";" >/dev/null 2>&1 ||
      echo "warning: throwaway database $CHECK_DB was left behind" >&2
  fi
  if [ "$code" -ne 0 ]; then
    echo "restore-check FAILED (exit $code)" >&2
  fi
  exit "$code"
}
trap cleanup EXIT

# ---------------------------------------------------------------- 1. the dump

if [ -z "$DUMP" ]; then
  DUMP="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'habit_tracker_*.sql.gz' |
    sort -r | head -n 1)"
  if [ -z "$DUMP" ]; then
    echo "no dump in $BACKUP_DIR — backup.sh has never produced one" >&2
    exit 1
  fi
  # Age in hours, computed from the file's own mtime rather than from its name:
  # a dump copied in from elsewhere keeps a truthful mtime and may carry any name.
  if [ -n "$(find "$DUMP" -mmin +"$((MAX_AGE_HOURS * 60))" -print -quit 2>/dev/null)" ]; then
    echo "freshest dump is older than $MAX_AGE_HOURS h: $DUMP" >&2
    echo "the nightly cron job is not running; yesterday is not recoverable." >&2
    exit 1
  fi
fi

if [ ! -f "$DUMP" ]; then
  echo "no such dump: $DUMP" >&2
  exit 1
fi
echo "dump: $DUMP"

# ------------------------------------------------- 2. what the last run said

if [ -f "$STATUS_FILE" ]; then
  echo "status: $(cat "$STATUS_FILE")"
  if grep -q "FAIL" "$STATUS_FILE"; then
    echo "the last run of backup.sh recorded a failure — see $STATUS_FILE" >&2
    exit 1
  fi
else
  echo "warning: no status file at $STATUS_FILE; backup.sh has not run since it was introduced" >&2
fi

# --------------------------------------------------------- 3. is it readable

if ! gzip -t "$DUMP" 2>/dev/null; then
  echo "dump is not a readable gzip stream: $DUMP" >&2
  exit 1
fi

# ------------------------------------------------------ 4. no secrets inside

FOUND="$(gzip -dc "$DUMP" | grep -E -c "$SECRET_PATTERNS" || true)"
if [ "${FOUND:-0}" -gt 0 ]; then
  echo "dump carries $FOUND line(s) matching a credential pattern." >&2
  echo "the dump is meant to hold no secrets at all (deploy/README.md)." >&2
  echo "inspect with: gzip -dc '$DUMP' | grep -nE '$SECRET_PATTERNS'" >&2
  exit 1
fi
echo "secrets: none of the known credential patterns appear in the dump"

# -------------------------------------------------------------- 5. restore it

psql_run -v ON_ERROR_STOP=1 -d postgres -c "CREATE DATABASE \"$CHECK_DB\";" >/dev/null
DB_CREATED="yes"
echo "restoring into throwaway database $CHECK_DB"
gzip -dc "$DUMP" | psql_run -v ON_ERROR_STOP=1 -q -d "$CHECK_DB" >/dev/null

# --------------------------------------------------------- 6. did anything come back

COUNTS="$(psql_run -At -F '|' -d "$CHECK_DB" -c "
  SELECT (SELECT count(*) FROM day),
         (SELECT count(*) FROM day_plan),
         (SELECT count(*) FROM plan_item),
         (SELECT count(*) FROM plan_mark);
")"
DAYS="$(printf '%s' "$COUNTS" | cut -d '|' -f 1)"
PLANS="$(printf '%s' "$COUNTS" | cut -d '|' -f 2)"
ITEMS="$(printf '%s' "$COUNTS" | cut -d '|' -f 3)"
MARKS="$(printf '%s' "$COUNTS" | cut -d '|' -f 4)"

echo "restored: days=$DAYS plans=$PLANS items=$ITEMS marks=$MARKS"

if [ "${DAYS:-0}" -eq 0 ]; then
  echo "the restored database has no days at all — this dump restores nothing." >&2
  exit 1
fi

echo "restore-check OK"
